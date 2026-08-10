/**
 * macUpdateInstaller — the I/O half of the macOS self-updater.
 *
 * Downloads a release asset, checks it against the SHA-512 published in
 * latest-mac.yml, unpacks the new .app into a hidden folder BESIDE the
 * installed one, and writes the script that swaps them after the app quits.
 *
 * Nothing here touches the installed app. The destructive step happens only in
 * the swap script, only after our process has exited, and only with a backup in
 * place. See macUpdate.cjs for the reasoning and the pure helpers.
 */

const fs = require('fs');
const fsp = require('fs/promises');
const os = require('os');
const path = require('path');
const https = require('https');
const crypto = require('crypto');
const { execFile } = require('child_process');
const { promisify } = require('util');

const {
  STAGING_DIR_NAME,
  STAGED_MARKER_NAME,
  buildSwapScript,
  stagedUpdateIsUsable,
} = require('./macUpdate.cjs');

const execFileAsync = promisify(execFile);

// Redirect budget for the GitHub release download (github.com → release-assets.githubusercontent.com).
const MAX_REDIRECTS = 5;
// The staged copy is a full second copy of a ~1 GB app, plus the download itself.
const REQUIRED_FREE_BYTES = 3 * 1024 * 1024 * 1024;

// The download owns 0-90% of the reported progress; staging owns the rest.
// The renderer's stall watchdog is reset only by a CHANGE in percent, and the
// ~1 GB `ditto` reports nothing, so without these staging ticks a slow disk
// makes a perfectly successful update report itself as timed out.
const DOWNLOAD_PROGRESS_CEILING = 90;
const STAGE_PROGRESS = { mounted: 92, copied: 96, verified: 98 };

/**
 * Stream a URL to disk, hashing as we go.
 *
 * Hashing during the download rather than re-reading afterwards matters here:
 * the asset is over half a gigabyte and re-reading it would double the wait on
 * a school laptop.
 */
function downloadWithHash(url, destPath, onProgress, redirectsLeft = MAX_REDIRECTS) {
  return new Promise((resolve, reject) => {
    // 'wx' fails if the path already exists, so a symlink planted at a
    // predictable temp path cannot redirect this write onto a user's document.
    const file = fs.createWriteStream(destPath, { flags: 'wx', mode: 0o600 });
    let settled = false;

    const done = (err, value) => {
      if (settled) return;
      settled = true;
      // pipe() does not tear down the counterpart, so an error on either side
      // would otherwise hold the socket and the file descriptor for the rest of
      // the session — and a deleted-but-open file keeps its disk blocks.
      file.destroy();
      if (err) reject(err);
      else resolve(value);
    };

    file.on('error', (err) => done(err));

    const get = (target, hops) => {
      const request = https.get(
        target,
        { headers: { 'User-Agent': 'RedactionTool-Updater', Accept: 'application/octet-stream' } },
        (res) => {
          const { statusCode, headers } = res;

          if (statusCode >= 300 && statusCode < 400 && headers.location) {
            res.resume();
            if (hops <= 0) {
              done(new Error('Too many redirects while downloading the update'));
              return;
            }
            get(new URL(headers.location, target).toString(), hops - 1);
            return;
          }

          if (statusCode !== 200) {
            res.resume();
            done(new Error(`Download failed with HTTP ${statusCode}`));
            return;
          }

          const total = Number(headers['content-length']) || 0;
          const hash = crypto.createHash('sha512');
          let received = 0;
          let lastReported = -1;

          res.on('data', (chunk) => {
            hash.update(chunk);
            received += chunk.length;
            if (total > 0 && onProgress) {
              const percent = Math.floor((received / total) * DOWNLOAD_PROGRESS_CEILING);
              // One event per whole percent — a 64 KB chunk each would be tens
              // of thousands of IPC messages.
              if (percent !== lastReported) {
                lastReported = percent;
                onProgress(percent);
              }
            }
          });

          res.on('error', (err) => done(err));

          let digest = null;
          file.on('finish', () => {
            digest = hash.digest('base64');
          });
          // Resolve on 'close', not 'finish': hdiutil is handed this path next
          // and needs the descriptor already released.
          file.on('close', () => {
            if (digest !== null) done(null, { sha512: digest, bytes: received });
          });

          res.pipe(file);
        }
      );

      request.on('error', (err) => done(err));
      request.setTimeout(120000, () => {
        request.destroy(new Error('The download timed out'));
      });
    };

    get(url, redirectsLeft);
  });
}

/** Free space on the volume holding `dir`, or null if it can't be determined. */
function freeBytesFor(dir) {
  try {
    const stats = fs.statfsSync(dir);
    return stats.bavail * stats.bsize;
  } catch {
    return null;
  }
}

/** Extract the .app out of a mounted disk image into `stagingDir`. */
async function stageFromDmg(dmgPath, stagingDir, onProgress) {
  // mkdtemp rather than a pid-derived name: the pid space is small enough to
  // pre-create every candidate, and mkdir(recursive) succeeds on an existing
  // symlink-to-directory.
  const mountParent = await fsp.mkdtemp(path.join(os.tmpdir(), 'redaction-update-mnt-'));
  const mountPoint = path.join(mountParent, 'vol');

  await execFileAsync('/usr/bin/hdiutil', [
    'attach', dmgPath,
    '-nobrowse', '-noautoopen', '-readonly',
    '-mountpoint', mountPoint,
  ]);
  if (onProgress) onProgress(STAGE_PROGRESS.mounted);

  try {
    const entries = await fsp.readdir(mountPoint);
    const apps = entries.filter((name) => name.endsWith('.app'));
    if (apps.length !== 1) {
      throw new Error('The downloaded disk image did not contain exactly one application');
    }

    const stagedApp = path.join(stagingDir, apps[0]);
    // `ditto`, not `cp -R`: it is the only copy that reliably preserves the
    // symlinks and extended attributes inside a framework-bearing .app bundle.
    await execFileAsync('/usr/bin/ditto', [path.join(mountPoint, apps[0]), stagedApp]);
    if (onProgress) onProgress(STAGE_PROGRESS.copied);
    return stagedApp;
  } finally {
    // Detaching can fail transiently while Spotlight still has the volume open.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await execFileAsync('/usr/bin/hdiutil', ['detach', mountPoint, '-quiet']);
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
    await fsp.rm(mountParent, { recursive: true, force: true }).catch(() => {});
  }
}

/** Extract the .app out of a zip archive into `stagingDir`. */
async function stageFromZip(zipPath, stagingDir, onProgress) {
  await execFileAsync('/usr/bin/ditto', ['-x', '-k', zipPath, stagingDir]);
  if (onProgress) onProgress(STAGE_PROGRESS.copied);
  const entries = await fsp.readdir(stagingDir);
  const apps = entries.filter((name) => name.endsWith('.app'));
  if (apps.length !== 1) {
    throw new Error('The downloaded archive did not contain exactly one application');
  }
  return path.join(stagingDir, apps[0]);
}

/** Read a single key out of a bundle's Info.plist. */
async function readPlistKey(appPath, key) {
  const { stdout } = await execFileAsync('/usr/libexec/PlistBuddy', [
    '-c', `Print :${key}`,
    path.join(appPath, 'Contents', 'Info.plist'),
  ]);
  return stdout.trim();
}

const readBundleVersion = (appPath) => readPlistKey(appPath, 'CFBundleShortVersionString');
const readBundleId = (appPath) => readPlistKey(appPath, 'CFBundleIdentifier');

/** Path of the marker recording what is currently staged. */
function stagedMarkerPath(appPath) {
  return path.join(path.dirname(appPath), STAGING_DIR_NAME, STAGED_MARKER_NAME);
}

/**
 * Return a previously staged update if it is still usable, else null.
 * Callers that get null should clean the staging directory.
 */
async function readStagedUpdate(appPath, expected) {
  try {
    const raw = await fsp.readFile(stagedMarkerPath(appPath), 'utf8');
    const marker = JSON.parse(raw);
    if (!stagedUpdateIsUsable(marker, expected || {})) return null;
    // The marker is only a claim — confirm the bundle is actually still there.
    await fsp.access(path.join(marker.stagedApp, 'Contents', 'Info.plist'));
    await fsp.access(marker.scriptPath);
    return marker;
  } catch {
    return null;
  }
}

/**
 * Delete a staging folder. It holds a full copy of the app — around a gigabyte
 * — so this runs whenever the staged content is not reusable.
 */
async function cleanStagingDir(appPath) {
  const stagingDir = path.join(path.dirname(appPath), STAGING_DIR_NAME);
  await fsp.rm(stagingDir, { recursive: true, force: true }).catch(() => {});
}

/**
 * Download and stage an update. Returns the arguments the swap script needs.
 * Throws on any problem; the caller falls back to the manual-download prompt.
 */
async function prepareMacUpdate({
  appPath, version, asset, downloadUrl, tempDir, expectedBundleId, onProgress,
}) {
  const parentDir = path.dirname(appPath);
  const stagingDir = path.join(parentDir, STAGING_DIR_NAME);

  // Both volumes matter: the staged copy lands beside the app, the download
  // lands in the temp dir, and they are not necessarily the same disk.
  for (const dir of new Set([parentDir, tempDir])) {
    const free = freeBytesFor(dir);
    if (free !== null && free < REQUIRED_FREE_BYTES) {
      throw new Error('There is not enough free space on this computer to install the update');
    }
  }

  // Start from clean: a half-finished staging folder from an earlier attempt
  // would leave a stale .app for the swap script to move into place.
  await fsp.rm(stagingDir, { recursive: true, force: true }).catch(() => {});
  await fsp.mkdir(stagingDir, { recursive: true });

  // A private 0700 directory, so the download path is neither predictable nor
  // pre-creatable by another process.
  const downloadDir = await fsp.mkdtemp(path.join(tempDir, 'redaction-update-'));
  const downloadPath = path.join(downloadDir, path.basename(new URL(downloadUrl).pathname));

  try {
    const { sha512, bytes } = await downloadWithHash(downloadUrl, downloadPath, onProgress);

    // FAIL CLOSED. This is the only check that the bytes are the ones the
    // release published, and a manifest missing the field must abort rather
    // than silently install whatever arrived. (It proves integrity, NOT
    // authenticity — see the header of macUpdate.cjs.)
    if (!asset.sha512) {
      throw new Error('The update manifest did not publish a checksum, so it was not installed');
    }
    if (sha512 !== asset.sha512) {
      throw new Error('The downloaded update failed its integrity check');
    }
    if (asset.size && Number(asset.size) !== bytes) {
      throw new Error('The downloaded update was not the expected size');
    }

    const stagedApp = downloadPath.toLowerCase().endsWith('.zip')
      ? await stageFromZip(downloadPath, stagingDir, onProgress)
      : await stageFromDmg(downloadPath, stagingDir, onProgress);

    // The identity check is the strict one: it is what stops a mis-picked or
    // substituted image installing as this app. The version is belt-and-braces
    // — the checksum already pinned the bytes to this release — and is NOT
    // fatal, because `mac.bundleShortVersion` or a pre-release tag can
    // legitimately make it differ from the release version.
    const stagedBundleId = await readBundleId(stagedApp);
    if (expectedBundleId && stagedBundleId !== expectedBundleId) {
      throw new Error(
        `The downloaded update is a different application (${stagedBundleId}), so it was not installed`
      );
    }
    const stagedVersion = await readBundleVersion(stagedApp).catch(() => null);
    if (stagedVersion && stagedVersion !== version) {
      console.warn(
        `Staged bundle reports version ${stagedVersion}, expected ${version} — continuing on identity match`
      );
    }
    if (onProgress) onProgress(STAGE_PROGRESS.verified);

    const scriptPath = path.join(stagingDir, 'swap.sh');
    await fsp.writeFile(scriptPath, buildSwapScript(), { mode: 0o755 });

    const staged = {
      version,
      bundleId: stagedBundleId,
      stagedApp,
      scriptPath,
      backupPath: path.join(stagingDir, 'previous.app'),
      stagingDir,
    };
    // Written last: its presence means everything above succeeded, so a
    // relaunch can reuse this instead of downloading half a gigabyte again.
    await fsp.writeFile(stagedMarkerPath(appPath), JSON.stringify(staged, null, 2), 'utf8');
    return staged;
  } catch (err) {
    await fsp.rm(stagingDir, { recursive: true, force: true }).catch(() => {});
    throw err;
  } finally {
    await fsp.rm(downloadDir, { recursive: true, force: true }).catch(() => {});
  }
}

module.exports = {
  prepareMacUpdate,
  readStagedUpdate,
  cleanStagingDir,
  freeBytesFor,
  downloadWithHash,
  stageFromDmg,
  stageFromZip,
  readBundleVersion,
  readBundleId,
};
