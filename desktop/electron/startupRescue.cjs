/**
 * What to tell the user when the redaction engine fails to start.
 *
 * The auto-updater is only set up once the engine is ready, so a release that
 * ships with a broken engine would quit on every launch and never hear about
 * the release that fixes it. Before giving up, main.cjs asks GitHub whether a
 * newer version exists and, if so, offers the download page instead of the
 * bare error. Pure so it can be unit-tested; main.cjs does the I/O.
 */

const RELEASES_URL = 'https://github.com/mrdavearms/student-doc-redactor/releases/latest';

// Long enough for a slow school network, short enough that a user staring at
// an empty screen is not left wondering whether anything is happening.
const RESCUE_CHECK_TIMEOUT_MS = 15000;

/**
 * @param {object} args
 * @param {string} args.failureMessage  why the engine did not start
 * @param {string} args.currentVersion  app.getVersion()
 * @param {{isUpdateAvailable: boolean, updateInfo?: {version?: string}} | null} args.checkResult
 *        autoUpdater.checkForUpdates() result, or null when the check failed or timed out
 * @returns {{kind: 'update', options: object, url: string} | {kind: 'error', title: string, message: string}}
 */
function startupFailureDialog({ failureMessage, currentVersion, checkResult }) {
  const latest = checkResult && checkResult.updateInfo && checkResult.updateInfo.version;
  if (checkResult && checkResult.isUpdateAvailable && latest) {
    return {
      kind: 'update',
      url: RELEASES_URL,
      options: {
        type: 'warning',
        title: 'Failed to Start',
        message: `The redaction engine could not start, and a newer version (${latest}) is available.`,
        detail:
          `You have version ${currentVersion}. Installing the newer version is the most likely fix.\n\n` +
          `What went wrong:\n${failureMessage}`,
        buttons: ['Download the new version', 'Quit'],
        defaultId: 0,
        cancelId: 1,
      },
    };
  }
  return {
    kind: 'error',
    title: 'Failed to Start',
    message:
      `${failureMessage}\n\n` +
      `If this keeps happening, download the latest version from:\n${RELEASES_URL}`,
  };
}

const PORT_IN_USE_MESSAGE =
  'Another copy of the redaction engine is already running on this computer.\n\n' +
  'Close any other copy of this app and try again. If you have just force-quit ' +
  'the app, restarting your computer will clear it.';

const ENGINE_DAMAGED_MESSAGE =
  'The redaction engine could not start because part of it is missing or damaged.\n\n' +
  'Installing the app again usually fixes this.';

/**
 * Why the engine exited before it was ready, judged from what it printed.
 *
 * Almost always it is the port being held by another copy (rule #55), and
 * that stays the default. But a broken engine (a missing or incompatible
 * package) also exits early, and telling those users to restart their computer
 * sends them the wrong way. uvicorn reports a port clash as "error while
 * attempting to bind" with no traceback; a failed import prints a traceback.
 */
function earlyExitMessage(stderrText) {
  const text = String(stderrText || '');
  if (text.includes('Traceback (most recent call last)') && !text.includes('attempting to bind')) {
    return ENGINE_DAMAGED_MESSAGE;
  }
  return PORT_IN_USE_MESSAGE;
}

module.exports = {
  startupFailureDialog,
  earlyExitMessage,
  PORT_IN_USE_MESSAGE,
  ENGINE_DAMAGED_MESSAGE,
  RELEASES_URL,
  RESCUE_CHECK_TIMEOUT_MS,
};
