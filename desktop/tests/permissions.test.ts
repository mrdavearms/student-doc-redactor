import { describe, it, expect } from 'vitest';
// @ts-expect-error — plain CJS module, loaded directly by the Electron main process.
import { isPermissionAllowed } from '../electron/permissions.cjs';

describe('isPermissionAllowed', () => {
  it('allows the clipboard write every Copy button needs', () => {
    // navigator.clipboard.writeText asks for this permission; refusing it
    // rejects with "NotAllowedError: Write permission denied".
    expect(isPermissionAllowed('clipboard-sanitized-write')).toBe(true);
  });

  it.each([
    'clipboard-read',
    'media',
    'geolocation',
    'notifications',
    'midi',
    'midiSysex',
    'pointerLock',
    'fullscreen',
    'openExternal',
    'display-capture',
    'hid',
    'serial',
    'usb',
    'fileSystem',
    'window-management',
    'unknown',
  ])('denies %s', (permission) => {
    expect(isPermissionAllowed(permission)).toBe(false);
  });

  it('denies anything that is not exactly the allowed name', () => {
    expect(isPermissionAllowed('Clipboard-Sanitized-Write')).toBe(false);
    expect(isPermissionAllowed('clipboard-sanitized-write ')).toBe(false);
    expect(isPermissionAllowed('')).toBe(false);
    expect(isPermissionAllowed(undefined)).toBe(false);
  });
});
