/**
 * Which browser permission requests the main window may be granted.
 *
 * The app needs no camera, microphone, location, notifications or anything
 * else a web page can ask for — with one exception. `navigator.clipboard
 * .writeText`, behind every Copy button (paste completion, de-identify
 * completion, no-PII-found), asks Electron for `clipboard-sanitized-write`.
 * Refusing it rejects the write with "NotAllowedError: Write permission
 * denied", so every Copy button silently does nothing.
 *
 * Reading the clipboard (`clipboard-read`) stays refused: the app never
 * reads it, and a page that could would see whatever the user last copied.
 *
 * Kept out of main.cjs so it can be unit-tested (see permissions.test.ts).
 */

const ALLOWED_PERMISSIONS = new Set(['clipboard-sanitized-write']);

/**
 * @param {string} permission  Electron permission name from the request handler.
 * @returns {boolean}          True only for an exactly-named allowed permission.
 */
function isPermissionAllowed(permission) {
  return ALLOWED_PERMISSIONS.has(permission);
}

module.exports = { isPermissionAllowed };
