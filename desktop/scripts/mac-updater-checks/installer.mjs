/**
 * Checks the I/O half of the macOS updater (electron/macUpdateInstaller.cjs):
 *   - mounting a .dmg and `ditto`-ing the .app out (framework symlinks intact)
 *   - reading bundle id and version back off the staged bundle
 *   - a real streaming download + base64 SHA-512 against the live release
 *   - the 'wx' open flag refusing a pre-existing path (symlink protection)
 *
 * Builds its own small disk image, so it does not need the ~570 MB release.
 * The one network call fetches `latest-mac.yml` from the latest release, which
 * also incidentally proves REPO_OWNER/REPO_NAME still point somewhere real.
 *
 * macOS only. Run via `npm run verify:mac-updater`.
 */
import { execFileSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ELECTRON_DIR = path.resolve(HERE, '..', '..', 'electron');
const installer = require(path.join(ELECTRON_DIR, 'macUpdateInstaller.cjs'));
const { REPO_OWNER, REPO_NAME } = require(path.join(ELECTRON_DIR, 'macUpdate.cjs'));

const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'redaction-installcheck-'));
process.on('exit', () => fs.rmSync(WORK, { recursive: true, force: true }));

let pass = 0, fail = 0;
const check = (label, actual, expected) => {
  if (String(actual) === String(expected)) { console.log(`  PASS  ${label}`); pass++; }
  else { console.log(`  FAIL  ${label} (got '${actual}', wanted '${expected}')`); fail++; }
};

// A fake .app with a real Info.plist plus an internal symlink, so we can
// confirm `ditto` preserves the bundle structure `cp -R` would mangle.
const srcRoot = path.join(WORK, 'src');
const appName = 'Redaction Tool.app';            // deliberately contains a space
const appDir = path.join(srcRoot, appName);
const fwVersions = path.join(appDir, 'Contents', 'Frameworks', 'Fake.framework', 'Versions');
fs.mkdirSync(path.join(appDir, 'Contents', 'MacOS'), { recursive: true });
fs.mkdirSync(path.join(fwVersions, 'A'), { recursive: true });
fs.symlinkSync('A', path.join(fwVersions, 'Current'));
fs.writeFileSync(path.join(appDir, 'Contents', 'MacOS', 'Redaction Tool'), '#!/bin/bash\n', { mode: 0o755 });
fs.writeFileSync(path.join(appDir, 'Contents', 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleShortVersionString</key><string>9.9.9</string>
  <key>CFBundleIdentifier</key><string>au.com.antigravity.redaction-tool</string>
  <key>CFBundleExecutable</key><string>Redaction Tool</string>
</dict></plist>
`);

console.log('== Build a test disk image ==');
const dmgPath = path.join(WORK, 'test.dmg');
execFileSync('/usr/bin/hdiutil', [
  'create', '-volname', 'Redaction Tool Test',
  '-srcfolder', srcRoot, '-ov', '-format', 'UDZO', '-quiet', dmgPath,
]);
check('disk image created', fs.existsSync(dmgPath), 'true');

console.log('== Mount + ditto the app out (with staging progress) ==');
const stagingDir = path.join(WORK, '.redaction-tool-update');
fs.mkdirSync(stagingDir, { recursive: true });
const ticks = [];
const stagedApp = await installer.stageFromDmg(dmgPath, stagingDir, (p) => ticks.push(p));

check('staged bundle name preserved', path.basename(stagedApp), appName);
check('executable present', fs.existsSync(path.join(stagedApp, 'Contents', 'MacOS', 'Redaction Tool')), 'true');
check(
  'framework symlink preserved (ditto, not cp)',
  fs.lstatSync(path.join(stagedApp, 'Contents', 'Frameworks', 'Fake.framework', 'Versions', 'Current')).isSymbolicLink(),
  'true'
);
// The renderer's stall watchdog only resets on a CHANGE of percent, so staging
// must emit rising values or a slow disk looks like a timed-out update.
check('staging emitted rising progress',
  new Set(ticks).size >= 2 && ticks[ticks.length - 1] > ticks[0], 'true');

console.log('== Read identity + version off the staged bundle ==');
check('CFBundleIdentifier', await installer.readBundleId(stagedApp), 'au.com.antigravity.redaction-tool');
check('CFBundleShortVersionString', await installer.readBundleVersion(stagedApp), '9.9.9');

console.log('== No stale mount left behind ==');
check('image detached',
  execFileSync('/sbin/mount').toString().includes('Redaction Tool Test') ? 'still-mounted' : 'detached',
  'detached');

console.log('== Streaming download + base64 SHA-512 against the live release ==');
const url = `https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download/latest-mac.yml`;
const dest = path.join(WORK, 'latest-mac.yml');
const { sha512, bytes } = await installer.downloadWithHash(url, dest, () => {});
const expected = execFileSync('/bin/sh', ['-c',
  `openssl dgst -sha512 -binary "${dest}" | openssl base64 -A`]).toString().trim();
check('followed redirects and downloaded', bytes > 0, 'true');
check('sha512 matches openssl (base64 form)', sha512, expected);

const yml = fs.readFileSync(dest, 'utf8');
check('published hash is base64, not hex',
  /^[A-Za-z0-9+\/]+=+$/.test(yml.match(/sha512:\s*(\S+)/)[1]), 'true');
// electron-builder substitutes dashes for spaces in the PUBLISHED name, even
// though the local artifact keeps them. If that ever changes, downloadUrlFor's
// dash-substitution stops matching the real URL and every update 404s.
const assetUrl = yml.match(/^\s*-\s*url:\s*(.+)$/m)[1].trim();
check('manifest asset name has no spaces (dash substitution)',
  /\s/.test(assetUrl) ? `has a space: ${assetUrl}` : 'no spaces', 'no spaces');

console.log('== The download refuses a pre-existing path (symlink protection) ==');
// 'wx' is what stops a planted symlink redirecting a ~570 MB write onto a
// student document. Prove it refuses rather than truncating.
const victim = path.join(WORK, 'precious.pdf');
fs.writeFileSync(victim, 'IRREPLACEABLE');
const trap = path.join(WORK, 'trap.dmg');
fs.symlinkSync(victim, trap);
let refused = false;
try {
  await installer.downloadWithHash(url, trap, () => {});
} catch {
  refused = true;
}
check('refused to write through the symlink', refused, 'true');
check('victim file untouched', fs.readFileSync(victim, 'utf8'), 'IRREPLACEABLE');

console.log(`\ninstaller: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
