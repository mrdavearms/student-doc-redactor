/**
 * Which URLs the main window is allowed to navigate to.
 *
 * The window renders only its own content — a local bundle when packaged, the
 * Vite dev server in development — so the only legitimate "navigation" is a
 * reload of the page already loaded. A link, a redirect or a `window.open` is
 * an escape, not a feature.
 *
 * This lives in its own module, separate from main.cjs, because it is the one
 * piece of the navigation guard that can be unit-tested: there is no Electron
 * main-process test harness, and the packaged case compares `file://` URLs,
 * where Windows ("file:///C:/...") is easy to get subtly wrong in a way that
 * would block the app from loading its OWN page. See navigation.test.ts.
 */

/**
 * @param {string} target   URL the window is trying to navigate to.
 * @param {string} appUrl   URL the window was loaded with.
 * @returns {boolean}       True only for the app's own page.
 */
function isAllowedNavigation(target, appUrl) {
  let url;
  let app;
  try {
    url = new URL(target);
    app = new URL(appUrl);
  } catch {
    // Unparseable on either side — never assume it is ours.
    return false;
  }

  if (url.protocol !== app.protocol) return false;

  if (app.protocol === 'file:') {
    // file: URLs have a null origin, so compare paths instead. Hash and query
    // are ignored: the renderer may legitimately add them, and neither changes
    // which document is loaded.
    try {
      return decodeURIComponent(url.pathname) === decodeURIComponent(app.pathname);
    } catch {
      return false;
    }
  }

  // Dev server: same origin only, so a redirect to another host is blocked.
  return url.origin === app.origin;
}

module.exports = { isAllowedNavigation };
