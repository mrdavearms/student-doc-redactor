import { describe, it, expect } from 'vitest';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { buildMenuTemplate } from '../electron/menu.cjs';

type Item = { label?: string; role?: string; submenu?: Item[] };

const roles = (template: Item[] | null): string[] =>
  (template ?? []).flatMap((m) => (m.submenu ?? []).map((i) => i.role ?? ''));

const mac = (isPackaged: boolean) =>
  buildMenuTemplate({ platform: 'darwin', isPackaged, appName: 'Redaction Tool' }) as Item[];
const win = (isPackaged: boolean) =>
  buildMenuTemplate({ platform: 'win32', isPackaged, appName: 'Redaction Tool' }) as Item[] | null;

describe('buildMenuTemplate — macOS', () => {
  it('keeps the Edit roles, or copy/paste stop working in text fields', () => {
    const r = roles(mac(true));
    for (const role of ['undo', 'redo', 'cut', 'copy', 'paste', 'selectAll']) {
      expect(r).toContain(role);
    }
  });

  it('has an app menu with About, Hide and Quit, and a Window menu', () => {
    const r = roles(mac(true));
    for (const role of ['about', 'hide', 'quit', 'minimize', 'zoom']) {
      expect(r).toContain(role);
    }
    expect(mac(true)[0].label).toBe('Redaction Tool');
  });

  it('never offers reload, which wipes the wizard', () => {
    for (const packaged of [true, false]) {
      const r = roles(mac(packaged));
      expect(r).not.toContain('reload');
      expect(r).not.toContain('forceReload');
    }
  });

  it('offers developer tools only in development', () => {
    expect(roles(mac(true))).not.toContain('toggleDevTools');
    expect(roles(mac(false))).toContain('toggleDevTools');
  });
});

describe('buildMenuTemplate — Windows', () => {
  it('has no menu at all when packaged', () => {
    expect(win(true)).toBeNull();
  });

  it('has only developer tools in development', () => {
    expect(roles(win(false))).toEqual(['toggleDevTools']);
  });
});
