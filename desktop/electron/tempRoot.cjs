/**
 * The folder Word conversions are written to.
 *
 * Converted PDFs are full, UNREDACTED copies of a student's document. Python
 * used to create and delete this folder itself, but its `atexit` cleanup never
 * runs when the backend is killed: Node's kill() ends python.exe forcibly on
 * Windows, and the 6-second SIGKILL fallback skips it on macOS. Electron
 * outlives the backend, so Electron owns the folder: it creates it, hands the
 * path to the backend, deletes it after the backend exits on any path, and
 * sweeps leftovers from earlier crashes at launch.
 *
 * Kept separate from main.cjs so it can be unit-tested (see tempRoot.test.ts).
 */
const fs = require('fs');
const path = require('path');

const PREFIX = 'redaction-tool-';
// Python's own fallback folder (a manual uvicorn or pytest run). Not ours to sweep.
const PYTHON_PREFIX = 'redaction-tool-py-';

/** Make a private (mkdtemp, mode 0700 on POSIX) directory under `tmpdir`. */
function createRoot(tmpdir) {
  return fs.mkdtempSync(path.join(tmpdir, PREFIX));
}

/** Delete `root` and everything in it. Returns false if it could not. */
function removeRoot(root) {
  try {
    fs.rmSync(root, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

/**
 * Remove leftover `redaction-tool-*` directories directly under `tmpdir`,
 * except `keep`. Symlinks are never followed or removed, and on POSIX only
 * directories owned by the current user are touched. Never throws.
 * @returns {string[]} the paths removed.
 */
function sweepStale(tmpdir, keep) {
  const removed = [];
  let names;
  try {
    names = fs.readdirSync(tmpdir);
  } catch {
    return removed;
  }
  for (const name of names) {
    if (!name.startsWith(PREFIX) || name.startsWith(PYTHON_PREFIX)) continue;
    const full = path.join(tmpdir, name);
    if (keep && full === keep) continue;
    try {
      const st = fs.lstatSync(full);
      if (!st.isDirectory()) continue; // lstat: a symlink is not a directory
      if (typeof process.getuid === 'function' && st.uid !== process.getuid()) continue;
      if (removeRoot(full)) removed.push(full);
    } catch {
      // Vanished or unreadable: leave it.
    }
  }
  return removed;
}

module.exports = { createRoot, removeRoot, sweepStale };
