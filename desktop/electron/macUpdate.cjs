/**
 * macUpdate — pure decision logic for the macOS self-updater.
 *
 * WHY THIS EXISTS
 * ---------------
 * electron-updater's macOS path (Squirrel.Mac) cannot install our builds: it
 * refuses any update whose code signature does not match the running app, and
 * an ad-hoc signature has a different fingerprint on every single build. Buying
 * an Apple Developer ID would fix that; until then macOS was notify-only and a
 * teacher had to re-download and re-drag the app by hand.
 *
 * So we do the install ourselves: download the release asset, unpack the new
 * .app beside the old one, and swap the bundles after the app quits. Detection
 * still comes from electron-updater — only the download+install half is ours.
 *
 * WHAT THE SHA-512 CHECK IS AND IS NOT
 * ------------------------------------
 * `latest-mac.yml` and the .dmg come from the SAME GitHub release over the SAME
 * channel, so verifying one against the other proves the download was not
 * CORRUPTED. It proves nothing about authenticity — anyone able to publish a
 * release can publish a matching hash. There is no signature and no out-of-band
 * trust anchor anywhere in this path. Do not describe it as a security control.
 *
 * The genuine safety property is the swap: it keeps a backup, and it never
 * deletes that backup until the replacement is confirmed in place.
 *
 * Everything here is pure so it can be unit-tested; all I/O lives in
 * macUpdateInstaller.cjs. See tests/macUpdate.test.ts.
 */

// These three MUST stay in step with `build.appId` and `build.publish` in
// package.json. Detection reads the packaged app-update.yml (generated from
// that config) while the download is built from these constants, so a repo
// rename would break updates SILENTLY — detection keeps working and every
// download 404s back to the manual prompt. macUpdate.test.ts asserts they match.
const REPO_OWNER = 'mrdavearms';
const REPO_NAME = 'student-doc-redactor';
const BUNDLE_ID = 'au.com.antigravity.redaction-tool';

/** Name of the hidden folder we stage the new app in, beside the current one. */
const STAGING_DIR_NAME = '.redaction-tool-update';
/** Records what is staged, so a relaunch reuses it instead of re-downloading. */
const STAGED_MARKER_NAME = 'staged.json';
/** Written by the swap script when it fails; read and cleared at next launch. */
const FAILURE_MARKER_NAME = 'update-failure.txt';
const SWAP_LOG_NAME = 'update-swap.log';

/**
 * Turn a `files[].url` from latest-mac.yml into a URL path segment.
 *
 * VERIFIED against a real build: electron-builder writes the *published* name
 * into the manifest, and that name already has spaces replaced by dashes
 * (`Redaction-Tool-1.6.2-arm64.dmg`) even though the local artifact on disk is
 * `Redaction Tool-1.6.2-arm64.dmg`. electron-updater does the same substitution
 * (`GitHubProvider`: `p.replace(/ /g, "-")`) rather than percent-encoding, so we
 * match it — percent-encoding a space here would 404.
 *
 * Returns null for anything that is not a plain filename, so a manifest we do
 * not control cannot point the download at another path or host.
 */
function safeAssetName(name) {
  if (typeof name !== 'string' || name.length === 0) return null;
  if (name.includes('/') || name.includes('\\') || name.includes('..')) return null;
  return encodeURIComponent(name.replace(/ /g, '-'));
}

/**
 * Build the GitHub download URL for a release asset.
 * Release tags in this repo are always `v<version>` (see CLAUDE.md, CI/CD).
 */
function downloadUrlFor({ owner = REPO_OWNER, repo = REPO_NAME, version, fileName }) {
  if (!version) return null;
  const safe = safeAssetName(fileName);
  if (!safe) return null;
  const tag = version.startsWith('v') ? version : `v${version}`;
  return `https://github.com/${owner}/${repo}/releases/download/${tag}/${safe}`;
}

/**
 * Choose which published file to download from a latest-mac.yml `files` list.
 *
 * Two rules that both exist to avoid silent breakage on a FUTURE release:
 *
 * 1. `.dmg` is preferred over `.zip`. The zip branch has never run in
 *    production; if a zip target is added later it must not silently become
 *    every Mac user's install path on the release that adds it.
 * 2. When several candidates remain, the architecture must disambiguate them.
 *    electron-updater has `filterFilesForArch()` for exactly this reason. If we
 *    still cannot tell them apart we return null, which falls back to a manual
 *    download rather than handing an Intel build to an Apple Silicon Mac.
 */
function pickMacAsset(files, arch = process.arch) {
  if (!Array.isArray(files)) return null;
  const candidates = files.filter(
    (f) => f && typeof f.url === 'string' && /\.(dmg|zip)$/i.test(f.url)
  );
  if (candidates.length === 0) return null;

  const dmgs = candidates.filter((f) => f.url.toLowerCase().endsWith('.dmg'));
  const pool = dmgs.length > 0 ? dmgs : candidates;
  if (pool.length === 1) return pool[0];

  const tokens = arch === 'arm64' ? ['arm64', 'aarch64'] : ['x64', 'x86_64', 'intel'];
  const matches = pool.filter((f) => tokens.some((t) => f.url.toLowerCase().includes(t)));
  return matches.length === 1 ? matches[0] : null;
}

/**
 * The shell script that performs the swap after the app has quit.
 *
 * It runs detached, outliving the process that spawned it. Positional args:
 *   $1 pid of the quitting app   $2 installed .app   $3 staged .app
 *   $4 backup path   $5 staging dir   $6 log file   $7 failure-marker file
 *
 * Three things here are load-bearing and were each a real defect first:
 *
 * - NOT `set -e`. An error must reach the rollback, not abort before it.
 * - The rollback's exit status IS checked before anything is deleted. An
 *   earlier version deleted the staging directory — which contains the backup —
 *   without checking, so a failed rollback left the user with no app at all.
 * - It writes a log and a failure marker. Everything here happens after the app
 *   has exited, with stdio discarded, so without these a failure is completely
 *   invisible and the app just silently re-downloads the update forever.
 *
 * Absolute paths for the binaries: this runs detached with the user's own
 * environment, and the installer half is already careful to do the same.
 *
 * No `xattr -dr com.apple.quarantine`. A programmatic download never carries a
 * quarantine flag, so it did nothing useful — while being an explicit Gatekeeper
 * bypass, and /usr/bin/xattr is a python3 shim that can pop the Command Line
 * Tools installer on a machine that lacks them.
 */
function buildSwapScript() {
  return `#!/bin/bash
# Generated by Redaction Tool. Replaces the app bundle after the app exits.
PID="$1"; TARGET="$2"; STAGED="$3"; BACKUP="$4"; STAGING="$5"; LOG="$6"; MARKER="$7"

log()  { /bin/echo "[$(/bin/date +%Y-%m-%dT%H:%M:%S)] $*" >> "$LOG" 2>/dev/null; }
fail() { log "FAILED: $*"; /bin/echo "$*" > "$MARKER" 2>/dev/null; }

log "swap starting (pid $PID)"

# Wait up to 60s for the old app to let go of its files.
for _ in $(/usr/bin/seq 1 300); do
  kill -0 "$PID" 2>/dev/null || break
  /bin/sleep 0.2
done
if kill -0 "$PID" 2>/dev/null; then
  fail "The app did not close in time, so the update was not installed."
  /bin/rm -rf -- "$STAGING"
  exit 1
fi

/bin/rm -rf -- "$BACKUP"
if ! /bin/mv -- "$TARGET" "$BACKUP"; then
  fail "The update could not replace the installed app."
  /bin/rm -rf -- "$STAGING"
  /usr/bin/open "$TARGET"
  exit 1
fi

if /bin/mv -- "$STAGED" "$TARGET"; then
  log "swap succeeded"
  /bin/rm -rf -- "$STAGING"
  # Give the old backend a moment to release port 8765, or the relaunched app
  # meets the "another copy is already running" dialog (see CLAUDE.md rule 55).
  /bin/sleep 2
  /usr/bin/open "$TARGET"
  exit 0
fi

# Swap failed. Restore the original, and only then clean up.
fail "The update could not be installed, so the previous version was restored."
if /bin/mv -- "$BACKUP" "$TARGET"; then
  log "rolled back to the previous version"
  /bin/rm -rf -- "$STAGING"
else
  log "ROLLBACK FAILED - the previous version is still at $BACKUP"
fi
/bin/sleep 2
/usr/bin/open "$TARGET"
exit 1
`;
}

/**
 * Why this install can't update itself in place — or null when it can.
 *
 * Every non-null answer sends the user down the existing manual-download path,
 * so an install we don't understand degrades to the old behaviour rather than
 * attempting a swap that might strand them without an app.
 */
function selfUpdateBlockedReason({ platform, isPackaged, appPath, appWritable, parentWritable }) {
  if (platform !== 'darwin') return 'not macOS';
  if (!isPackaged) return 'development build';
  if (typeof appPath !== 'string' || !appPath.endsWith('.app')) {
    return 'not an application bundle';
  }
  // Running straight from the mounted disk image: there is nothing installed to
  // replace, and /Volumes is read-only. They need to drag it across first.
  if (appPath.startsWith('/Volumes/')) return 'running from the disk image';
  if (!parentWritable || !appWritable) return 'no permission to replace the app';
  return null;
}

/**
 * Is a previously staged update still usable for the version now on offer?
 *
 * Without this the staging folder was deleted at every launch and a pending
 * update was re-downloaded in full — ~568 MB per launch, indefinitely, for
 * anyone who kept postponing the restart.
 */
function stagedUpdateIsUsable(marker, { version, bundleId }) {
  if (!marker || typeof marker !== 'object') return false;
  if (!marker.version || !marker.stagedApp || !marker.scriptPath) return false;
  if (version && marker.version !== version) return false;
  if (bundleId && marker.bundleId && marker.bundleId !== bundleId) return false;
  return true;
}

module.exports = {
  REPO_OWNER,
  REPO_NAME,
  BUNDLE_ID,
  STAGING_DIR_NAME,
  STAGED_MARKER_NAME,
  FAILURE_MARKER_NAME,
  SWAP_LOG_NAME,
  safeAssetName,
  downloadUrlFor,
  pickMacAsset,
  selfUpdateBlockedReason,
  stagedUpdateIsUsable,
  buildSwapScript,
};
