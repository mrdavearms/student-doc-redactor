# macOS In-App Update — Investigation & Options

> **Status:** Investigation complete, no code written. Decision deferred.
> **Date:** 27 July 2026 · **App version at time of investigation:** 1.5.0
> **Trigger:** "Improve the update process so it updates within itself and then restarts on its own, rather than having to download a file from GitHub and then run that file."

---

## Summary

**Windows already does this.** `quitAndInstall(true, true)` in `desktop/electron/main.cjs` downloads in the background, installs silently and relaunches. Nothing to fix there.

**macOS is the platform doing the manual DMG dance**, and it is deliberate — `setupAutoUpdater()` hard-codes `canAutoUpdate = process.platform === 'win32'`.

The blocker is not a bug. It is that the Mac build is **ad-hoc signed**, and Squirrel.Mac (the engine behind `electron-updater` on macOS) requires a real code signature. Testing on macOS 26.5.2 confirmed there is **no free route to silent self-update that does not involve the app stripping `com.apple.quarantine` from its own downloaded update.**

Three free routes and one paid route are specified below. **No route was selected.**

---

## Evidence gathered

All of the following was measured on this machine (macOS 26.5.2, build 25F84), not inferred.

### 1. The shipped Mac app is ad-hoc signed

```
$ codesign -dv --verbose=2 "desktop/release/mac-arm64/Redaction Tool.app"
Identifier=au.com.antigravity.redaction-tool
CodeDirectory v=20500 flags=0x10002(adhoc,runtime)
Signature=adhoc
TeamIdentifier=not set
```

Squirrel.Mac validates a downloaded update against the *running* app's designated requirement. For an ad-hoc signature that requirement is cdhash-based, so it changes on every build and can never match a successor. [Squirrel.Mac requires a codesigned app](https://github.com/electron/electron/issues/36640).

### 2. Only a `.dmg` is published — Squirrel cannot apply a DMG

Release v1.5.0 assets:

| Asset | Size |
|---|---|
| `Redaction-Tool-1.5.0-arm64.dmg` | 595 MB |
| `Redaction-Tool-1.5.0-arm64.dmg.blockmap` | 619 KB |
| `Redaction-Tool-Setup-1.5.0.exe` | 554 MB |
| `Redaction-Tool-Setup-1.5.0.exe.blockmap` | 577 KB |
| `latest-mac.yml` / `latest.yml` | 357 B each |

`package.json` → `build.mac.target` is `dmg` only. Any auto-update route needs a `zip` target added.

### 3. The installed app carries a quarantine flag, and Gatekeeper rejects it

```
$ xattr -l "/Applications/Redaction Tool.app"
com.apple.quarantine: 0381;6a667d78;Chrome;9A460C2D-...

$ spctl -a -t exec -vvv "/Applications/Redaction Tool.app"
rejected

$ codesign --verify --deep --strict "/Applications/Redaction Tool.app"
valid on disk / satisfies its Designated Requirement
```

It runs only because the install was approved by hand once.

**This is the load-bearing fact for any self-updater:** macOS propagates the quarantine flag from a quarantined process to files that process writes. An updater running inside this app hands the flag straight to whatever it downloads. That matches the behaviour [reported to Apple from Ventura 13.1 onward](https://developer.apple.com/forums/thread/730314) — the freshly unpacked bundle is quarantined and the old app cannot launch it. Apple separately advises [avoiding bundle self-modification](https://developer.apple.com/forums/thread/121310).

### 4. Gatekeeper test on macOS 26.5.2 (the decisive one)

A minimal Mach-O `.app` bundle was built and ad-hoc signed with hardened runtime — the same signature posture as the real build (`Signature=adhoc`, `TeamIdentifier=not set`) — then launched under both conditions:

| Scenario | `spctl` verdict | Actually launched? |
|---|---|---|
| Ad-hoc + `com.apple.quarantine` set (what a self-downloaded update inherits) | `rejected` | **No — blocked** |
| Ad-hoc + `xattr -cr` to strip quarantine | `rejected` | **Yes — launched** |

Two conclusions:

1. A self-downloaded update **will not run** unless the quarantine flag is removed.
2. Stripping the flag **does** work today, even though `spctl` still reports `rejected` — which is precisely why it is the kind of gap Apple narrows over time.

See the appendix for the reproduction script.

### 5. Notarisation groundwork is already done

If the paid route is ever taken, the usually-painful part is complete:

- `desktop/assets/entitlements.mac.plist` already declares `allow-jit`, `allow-unsigned-executable-memory` and `disable-library-validation` — exactly what a bundled-Python app needs to pass notarisation.
- `hardenedRuntime: true` is already set.
- 151 nested `.so`/`.dylib` files exist across `bundled-python`/`bundled-tesseract`; electron-builder signs nested code automatically once an identity is present.
- `.github/workflows/release.yml` has **no** signing config yet — greenfield.

### 6. Cost of the paid route

[AU$149/year](https://ambsandigital.com/apple-developer-program-fee-2026/) (Apple prices the Developer Program in local currency; the widely-quoted US$99 is the US figure). Individual enrolment needs no D-U-N-S number and is normally approved quickly, but the certificate carries a personal name. Organisation enrolment shows "Antigravity" instead, but requires a D-U-N-S number and a registered legal entity, and can take weeks.

**Decision on 27 July 2026: not investing in the fee yet.**

---

## Route A — Developer ID signing + notarisation (PAID, deferred)

The only route that yields a genuinely supported silent update on macOS, and the only one that also removes the "unidentified developer" warning teachers hit on first install.

**Work required:**

1. Enrol in the Apple Developer Program (individual).
2. Add `zip` to `build.mac.target` alongside `dmg`.
3. Add `"notarize": true` under `build.mac` in `desktop/package.json`.
4. Add CI secrets: `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`.
5. Delete the `canAutoUpdate` special-case in `setupAutoUpdater()` — let it be `true` on all platforms.
6. Drop the `update-available-manual` IPC path and its `useUpdater` branch (or keep as a fallback).

**Known costs:**

- Notarisation adds roughly 10–20 minutes to the Mac CI job for a ~600 MB artifact.
- **Every existing Mac user must download manually one final time.** An ad-hoc install cannot validate a signed successor. Flag this loudly in the release notes for whichever version makes the switch.
- Untested: how the 151 bundled binaries behave through a real notarisation run. Cannot be verified without a certificate in hand.

**Upside beyond the updater:** `electron-updater` [supports differential downloads on macOS zip via blockmaps](https://www.electron.build/docs/features/auto-update/), so repeat updates would fetch only changed blocks rather than the full ~600 MB.

---

## Route 1 — Full self-update with quarantine strip (FREE, delivers the original ask)

Reproduces the Windows experience on macOS: in-app progress, "Restart & Install", app relaunches updated.

**Requires accepting** that the app removes `com.apple.quarantine` from an update it has just downloaded and hash-verified. The integrity guarantee is equivalent to a manual download (HTTPS from GitHub + SHA-512 from `latest-mac.yml`), but it is a homegrown security-sensitive code path inside a PII tool, and Apple may tighten it in future.

**Files:**

- Modify: `desktop/package.json` — add `zip` to `build.mac.target`
- Modify: `desktop/electron/main.cjs` — new updater module wiring + IPC
- Create: `desktop/electron/mac-updater.cjs` — download, verify, extract, swap
- Modify: `desktop/electron/preload.cjs` — no new surface if IPC channel names are reused
- Modify: `desktop/src/hooks/useUpdater.ts` — macOS now follows the `downloading → ready` path
- Modify: `desktop/src/components/UpdateBanner.tsx` — remove the macOS manual-download branch

**Flow:**

1. `autoUpdater.checkForUpdates()` still handles *detection* — it returns `updateInfo.files[]` with `url` and `sha512`. Do not call `downloadUpdate()` on macOS; Squirrel would reject the ad-hoc bundle.
2. Resolve the `.zip` asset URL from the publish config + version. Download it to `app.getPath('temp')` with `net.request`, emitting `download-progress` so the existing UI and its stall watchdog work unchanged.
3. Verify SHA-512 against the value from `latest-mac.yml`. **Abort on mismatch** — this check is the entire trust anchor for the route. Never install an unverified bundle.
4. Extract with `ditto -x -k <zip> <staging>`.
5. `xattr -cr <staging>/Redaction Tool.app` to clear the inherited quarantine flag.
6. Sanity-check the staged bundle (`Contents/MacOS/Redaction Tool` exists and is executable) before touching the installed copy.
7. On "Restart & Install": write a detached helper shell script to temp that waits for the parent PID to exit, `mv`s the old bundle aside, `mv`s the new one into place, `open`s it, then deletes itself. Spawn it with `detached: true, stdio: 'ignore'`, then `app.quit()`. Do **not** write into the live bundle — swap whole directories atomically, or the code seal breaks mid-update.
8. Keep the old bundle until the new one launches successfully, then remove it.

**Preconditions to check before offering the update at all** (fall back to the current manual banner if any fail):

- The app is running from a writable location — test with `fs.access(path.dirname(bundlePath), fs.constants.W_OK)`. `/Applications` is `drwxrwxr-x root:admin`, so **admin users can write to it and non-admin users cannot.** A teacher on a school-managed Mac will typically hit this.
- The app is not running from a mounted DMG or a translocated path (`/private/var/folders/.../AppTranslocation/`).
- Free disk space exceeds roughly 2× the download size.

**Test coverage:** `desktop/tests/` covers pure modules only, and this is Electron-main code, so there is no existing harness for it. Extract the pure parts — URL resolution from version, SHA-512 comparison, precondition evaluation — into a testable module with vitest coverage, and verify the swap-and-relaunch by hand on a real build.

---

## Route 2 — In-app download + auto-mount (FREE, conservative)

Removes the "go to GitHub and find the right file" hunt without touching Gatekeeper or hand-rolling anything security-sensitive.

Steps 1–3 of Route 1 (detect, download the **DMG** with in-app progress, verify SHA-512), then `shell.openPath(dmgPath)` to mount it — macOS opens the drag-to-Applications window automatically. The teacher drags the icon as they do today.

No quarantine flag is touched, so first-launch approval behaves exactly as it does now. The app does **not** restart itself, so this does not fully deliver the original ask.

**Files:** `desktop/electron/main.cjs`, `desktop/src/hooks/useUpdater.ts`, `desktop/src/components/UpdateBanner.tsx`. No build config change (the DMG already exists).

---

## Route 3 — Deep-link the DMG (FREE, ~30 minutes)

`RELEASES_URL` in `desktop/src/hooks/useUpdater.ts:17` currently points at the releases *page*. Point `downloadLatest()` at the versioned asset instead, so one click starts the download:

```
https://github.com/mrdavearms/student-doc-redactor/releases/download/v{version}/Redaction-Tool-{version}-arm64.dmg
```

The version is already available from the `update-available-manual` IPC payload. Keep the releases page as the fallback when the version is unknown (the `{ status: 'error' }` branch has no version).

Everything else stays as-is. Smallest possible change; smallest possible win.

---

## Recommendation

**Route A is the correct long-term answer** and should be revisited when AU$149/year is worth it — it is the only supported path, and it also retires the first-launch scare warning, which is arguably worth more to teachers than the updater itself.

Until then, **Route 1 is the only free option that delivers the original request**, at the cost of a quarantine-strip in a PII tool and a fallback path for non-admin users. **Route 2** is the risk-free way to remove most of the friction without that tradeoff.

**Revisit trigger:** any decision to code-sign for a different reason (e.g. school IT refusing to deploy an unsigned app) makes Route A nearly free to add on top, since notarisation entitlements and hardened runtime are already configured.

---

## Appendix — Gatekeeper test reproduction

Builds a minimal ad-hoc-signed app with hardened runtime and launches it with and without the quarantine flag. Test artifacts were written to a scratchpad outside the repo.

```bash
D="$PWD/gktest"; rm -rf "$D"; mkdir -p "$D/Test.app/Contents/MacOS"; cd "$D"

cat > t.c <<EOF
#include <stdio.h>
int main(void){ FILE*f=fopen("$D/marker.txt","w"); fputs("LAUNCHED\n",f); fclose(f); return 0; }
EOF
clang -o Test.app/Contents/MacOS/Test t.c

cat > Test.app/Contents/Info.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Test</string>
<key>CFBundleIdentifier</key><string>au.com.antigravity.gktest</string>
<key>CFBundleName</key><string>Test</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1.0</string>
</dict></plist>
EOF

# Same signature posture as the shipped build.
codesign --force --deep --options runtime --sign - Test.app

# CASE 1 — quarantined, as an updater-downloaded bundle would be.
xattr -w com.apple.quarantine "0081;00000000;TestUpdater;" Test.app
xattr -w com.apple.quarantine "0081;00000000;TestUpdater;" Test.app/Contents/MacOS/Test
rm -f marker.txt; open -W Test.app; sleep 1
[ -f marker.txt ] && echo "LAUNCHED" || echo "BLOCKED"     # => BLOCKED

# CASE 2 — quarantine stripped, the workaround Route 1 depends on.
xattr -cr Test.app
rm -f marker.txt; open -W Test.app; sleep 1
[ -f marker.txt ] && echo "LAUNCHED" || echo "BLOCKED"     # => LAUNCHED
```
