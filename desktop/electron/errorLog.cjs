/**
 * Bounded append for the local error log.
 *
 * The log sits in userData and could otherwise grow without limit and hold
 * very long entries. Each entry is cut to `maxEntryBytes`, and when the file
 * would pass `maxFileBytes` it is renamed to `<file>.1` (replacing any earlier
 * one) so at most about two files' worth is ever kept.
 *
 * Kept separate from main.cjs so it can be unit-tested (see errorLog.test.ts).
 */
const fs = require('fs');

function appendBounded(file, entry, maxEntryBytes = 8192, maxFileBytes = 1048576) {
  let buf = Buffer.from(entry, 'utf8');
  if (buf.length > maxEntryBytes) {
    buf = Buffer.concat([buf.subarray(0, maxEntryBytes - 1), Buffer.from('\n')]);
  }
  let size = 0;
  try {
    size = fs.statSync(file).size;
  } catch {
    // No file yet.
  }
  if (size + buf.length > maxFileBytes) {
    fs.renameSync(file, file + '.1'); // replaces an earlier .1 on POSIX and Windows
  }
  fs.appendFileSync(file, buf);
}

module.exports = { appendBounded };
