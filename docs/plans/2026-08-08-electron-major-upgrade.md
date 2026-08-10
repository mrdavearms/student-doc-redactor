# Electron major upgrade — closing GHSA-9f4c-93c8-jc8g

**Status:** planned, not started
**Written:** 8 August 2026
**Revised:** 10 August 2026 — after v1.7.0/v1.7.1 the macOS updater works completely differently, and step 7 as originally written would have had someone undo it. Claims re-verified against the codebase on the same date.
**Trigger:** the one remaining `npm audit` high, and the only advisory in the August batch that both ships to users and has no in-range fix.

> **Do this AFTER at least one real-world macOS self-update has been seen to work** (1.7.0 → 1.7.1 is the first). Two reasons: if the Electron bump breaks updating, you want a known-good updater already in users' hands to ship the fix through — otherwise every Mac user is back to manual installs and there is no remote lever. And if you bump first and an update then fails, you cannot tell whether the cause is the new updater or the new Electron. One variable at a time.

---

## Why this needs a major bump

`electron@40.10.6` (current) is affected by **GHSA-9f4c-93c8-jc8g** — a sandboxed iframe can bypass the `allow-popups` restriction via the OpenURL navigation path.

The advisory has three affected ranges, and the shape of them is the whole problem:

| Range | First patched |
|---|---|
| `< 39.8.10` | 39.8.10 |
| `>= 40.0.0-alpha.1, < 41.10.3` | **41.10.3** |
| `>= 42.0.0-alpha.1, < 42.0.1` | 42.0.1 |

There is **no 40.x patch and there never will be**. Electron supports the latest three majors, which is currently 41/42/43 — the 40 line is already out of support, which is exactly why the fix for that range landed in 41.10.3 instead of a 40.10.x. Staying on 40 means staying vulnerable and, more importantly, means receiving no future Chromium security fixes at all.

## Actual exposure today: none

Worth stating plainly so this is scheduled honestly rather than panicked over.

The vulnerability requires attacker-controlled web content inside a sandboxed iframe. This app has:

- **no iframes and no `<webview>` anywhere** in `desktop/src` or `desktop/electron`
- production content loaded via `mainWindow.loadFile(dist/index.html)` — local files only
- the single `loadURL` call is the Vite dev server, dev builds only
- no remote content rendered at any point; the backend is `127.0.0.1` only
- `contextIsolation: true`, `nodeIntegration: false`, renderers sandboxed
- window-opening and off-app navigation are **already denied** — see step 2, which has since landed as `electron/navigation.cjs`

All of the above re-verified 10 August 2026, not assumed.

So this is **not an emergency**. It is a "do it in the next release" item. The real driver is falling off a supported Electron line, not this specific CVE.

## Why the upgrade should be low-risk

The app's Electron API surface is very small and entirely composed of long-stable APIs:

`app` · `BrowserWindow` · `dialog` · `ipcMain`/`ipcRenderer` · `contextBridge` · `shell.openExternal` · `webContents.send`

There is no `session`, `protocol`, `Menu`, `Tray`, or `nativeTheme` usage (the `session` hits in `main.cjs` are comments). There are **no native Node modules** — Python runs as a separate child process, so there is nothing to rebuild against a new ABI. And every one of 40/41/42/43 targets Node `^24.9.0`, so the bundled Node major does not move either.

The risk is therefore concentrated in **packaging and runtime behaviour**, not API breakage.

---

## Recommendation: go to 43.x (latest), not 41.10.3

| Option | Pros | Cons |
|---|---|---|
| **41.10.4** | Smallest delta; clears the advisory | 41 is the *oldest* supported line — this repeats in a few months |
| 42.8.1 | Middle ground | Same problem, later |
| **43.3.0 (recommended)** | Longest support runway; one test cycle instead of two | Largest Chromium delta to eyeball |

Given the tiny API surface, the marginal risk of 43 over 41 is small and buys roughly a year rather than a couple of months. If the smoke test throws up anything odd, 41.10.4 is the documented fallback — it still closes the advisory.

**Do not reach for `npm audit fix --force` to do this.** It resolves to electron@43 as a side effect, with no test pass and no version pinning discipline.

---

## Steps

1. **Branch off `test`.** `git checkout test && git checkout -b chore/electron-43`

2. ~~**Interim hardening, independent of the version bump.**~~ **DONE — nothing to do here.** This landed as `electron/navigation.cjs`: `main.cjs` now installs `setWindowOpenHandler` (deny) and a `will-navigate` guard backed by the pure `isAllowedNavigation()` allow-list, which is unit-tested in `desktop/tests/navigation.test.ts`. External links go through `shell.openExternal` via the `open-external` IPC handler, so nothing legitimate needs `window.open` or in-place navigation. Keep it regardless of what happens to the version bump.

3. **Bump.** `cd desktop && npm install --save-dev electron@^43.3.0`, then confirm `npm ls electron` shows a single 43.x and `npm audit` is clean.

4. **Static gates** (all must match the current baseline):
   - `npm run build` — tsc + vite clean
   - `npm test` — **166 passing** across 11 files
   - `npm run lint` — **exactly 7 errors + 1 warning**, no more
   - `node --check electron/main.cjs`
   - `npm run verify:mac-updater` — 43 checks over the swap script, installer I/O and staged-update persistence. The installer check reads the **live release manifest**, so it is the one that catches asset-naming or format changes caused by a toolchain bump.

5. **Dev smoke test** — `npm run dev:electron`. There is no Electron-main unit harness, so this is the real verification:
   - window opens at 1100×750; macOS `titleBarStyle: 'hiddenInset'` still renders correctly
   - backend health check passes and the window appears (no "engine stopped" dialog)
   - **launch a second copy** — must focus the existing window, not open a broken one (rule #55)
   - folder picker, file picker, and Save As dialogs all return paths
   - `shell.openExternal` works from the sidebar's GitHub link
   - run one document end-to-end through **both** pathways
   - quit and confirm no orphaned `python`/`uvicorn` process survives

6. **Packaged build, per platform.** This is where Electron majors actually bite:
   - `npm run dist:mac` → install the `.dmg` on a clean-ish macOS, confirm the ad-hoc signature still lets it launch past Gatekeeper with the documented bypass, and that bundled Python + Tesseract resolve via `process.resourcesPath`
   - **Check the signature explicitly — do not assume it:**
     ```
     codesign -dv --verbose=2 "release/mac-arm64/Redaction Tool.app"
     ```
     Expect `Identifier=au.com.antigravity.redaction-tool` and `flags=0x10002(adhoc,runtime)`. If it says `Identifier=Electron` / `linker-signed`, signing was silently skipped.

     **This is not hypothetical.** An `npm audit fix` moved electron-builder 26.8.1 → 26.15.3 in August 2026, which removed its automatic ad-hoc fallback; v1.6.1 through v1.7.0 shipped with no ad-hoc signature and nobody noticed, because the app still runs. `mac.identity: "-"` now forces it, but a runtime/toolchain bump is exactly the class of change that broke it before. Also confirm the entitlements survived — ad-hoc signing with `hardenedRuntime` needs `com.apple.security.cs.disable-library-validation` or the app will not launch once it loads the bundled dylibs.
   - `npm run dist:win` → same for the NSIS `.exe` on Windows
   - Both: confirm the backend spawns from the bundled interpreter, not a system one

7. **Auto-update regression** — the highest-value check, because it is the one thing that can strand existing users.

   > **CHANGED SINCE THIS PLAN WAS WRITTEN.** macOS is **no longer notify-only**. As of v1.7.0 it installs updates itself via `electron/macUpdate.cjs` + `electron/macUpdateInstaller.cjs`; electron-updater only does the *detection*. Do **not** "restore" `canAutoUpdate = process.platform === 'win32'` as the gate for the whole macOS path — that would undo the feature. `autoDownload` staying `false` on macOS is correct and expected.

   - The updater now spans **six** files (CLAUDE.md, Auto-Update): `main.cjs` → `macUpdate.cjs` + `macUpdateInstaller.cjs` → `preload.cjs` → `useUpdater.ts` → `UpdateBanner.tsx`/`UpdateCard.tsx`.
   - Windows NSIS auto-update must still work through electron-updater, unchanged.
   - macOS must still **download, verify, stage and swap** on its own. The swap is a detached `/bin/bash` script that outlives the app — an Electron major that changes process teardown or exit timing is exactly what could break it.
   - **Test the real macOS path end-to-end**, using the method that is now proven (CLAUDE.md, Auto-Update): build with the version set *below* the latest published release, ad-hoc sign it as CI does, install it to `/Applications`, and let it update itself to the real release. Confirm afterwards: version changed, app relaunched itself, backend healthy on 8765, staging folder gone, and `~/Library/Application Support/redaction-tool/update-swap.log` reads `swap succeeded` with no failure marker beside it.
   - `electron-updater` is only doing detection on macOS now, so the blast radius there is smaller than it was — but Windows still relies on it fully.

8. **Version sync before tagging** (CLAUDE.md release rules): bump `desktop/package.json` **and both** `version` fields in `desktop/package-lock.json` to match the tag. `verify-version` hard-fails the release otherwise.

9. **Merge `test` → `main` only after confirming with Dave**, then tag.

---

## Rollback

The bump is two files (`package.json`, `package-lock.json`). If the packaged build or the updater misbehaves, revert those and rebuild — no application code depends on the Electron version, so there is nothing else to unwind. Keep step 2's hardening; it is independent.

## Definition of done

- `npm audit` reports 0 vulnerabilities
- Dependabot's alert for GHSA-9f4c-93c8-jc8g closes on `main`
- A Windows user on the previous version auto-updates to the new one successfully
- **A macOS user on the previous version self-updates successfully** — downloaded, verified, swapped, relaunched, with `swap succeeded` in the log
- **The packaged macOS app still reports `Identifier=au.com.antigravity.redaction-tool`, `flags=(adhoc,runtime)`**
- CLAUDE.md's dependency-advisories note and this file are updated to say it is done
