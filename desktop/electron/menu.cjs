/**
 * The application menu, as a plain template for Menu.buildFromTemplate().
 *
 * Without an explicit menu Electron ships its default one: View → Reload /
 * Force Reload (Cmd+R / Ctrl+R wipes the whole wizard mid-run), Toggle
 * Developer Tools, and on Windows a menu bar drawn across the top of the app
 * with a Help menu linking to electronjs.org.
 *
 * macOS must keep an Edit menu. On a Mac the clipboard shortcuts (Cmd+C,
 * Cmd+V, Cmd+A, Cmd+Z) are delivered through menu items, not by the text
 * field itself — remove the Edit menu and copy/paste silently stop working in
 * every text box, including the paste pathway's textarea. Windows handles
 * those shortcuts in the text field, so it needs no menu at all.
 *
 * Kept separate from main.cjs so it can be unit-tested (see menu.test.ts).
 *
 * @param {{ platform: string, isPackaged: boolean, appName: string }} opts
 * @returns {object[] | null}  null means "no menu" (Menu.setApplicationMenu(null)).
 */
function buildMenuTemplate({ platform, isPackaged, appName }) {
  const devView = isPackaged
    ? []
    : [{ label: 'View', submenu: [{ role: 'toggleDevTools' }] }];

  if (platform !== 'darwin') {
    return devView.length ? devView : null;
  }

  return [
    {
      label: appName,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    ...devView,
    {
      label: 'Window',
      submenu: [{ role: 'minimize' }, { role: 'zoom' }],
    },
  ];
}

module.exports = { buildMenuTemplate };
