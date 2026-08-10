/**
 * Checks staged-update persistence — the fix for re-downloading ~570 MB on
 * every launch when a user postpones the restart.
 *
 * Runs against a fake app path in a temp directory, so nothing in
 * /Applications is touched and no bogus update can be clicked.
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ELECTRON_DIR = path.resolve(HERE, '..', '..', 'electron');
const installer = require(path.join(ELECTRON_DIR, 'macUpdateInstaller.cjs'));
const { BUNDLE_ID, STAGING_DIR_NAME } = require(path.join(ELECTRON_DIR, 'macUpdate.cjs'));

const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'redaction-persistcheck-'));
process.on('exit', () => fs.rmSync(WORK, { recursive: true, force: true }));

let pass = 0, fail = 0;
const check = (label, actual, expected) => {
  if (String(actual) === String(expected)) { console.log(`  PASS  ${label}`); pass++; }
  else { console.log(`  FAIL  ${label} (got '${actual}', wanted '${expected}')`); fail++; }
};

const appPath = path.join(WORK, 'Redaction Tool.app');
const stagingDir = path.join(WORK, STAGING_DIR_NAME);
const stagedApp = path.join(stagingDir, 'Redaction Tool.app');
const scriptPath = path.join(stagingDir, 'swap.sh');

function stage(marker) {
  fs.rmSync(stagingDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(stagedApp, 'Contents'), { recursive: true });
  fs.writeFileSync(path.join(stagedApp, 'Contents', 'Info.plist'), '<plist/>');
  fs.writeFileSync(scriptPath, '#!/bin/bash\n', { mode: 0o755 });
  fs.writeFileSync(path.join(stagingDir, 'staged.json'), JSON.stringify(marker));
}

const good = {
  version: '9.9.9', bundleId: BUNDLE_ID, stagedApp, scriptPath,
  backupPath: path.join(stagingDir, 'previous.app'), stagingDir,
};

console.log('== A staged update is re-adopted after a relaunch ==');
stage(good);
let got = await installer.readStagedUpdate(appPath, { bundleId: BUNDLE_ID });
check('adopted', got?.version, '9.9.9');
check('points at the staged bundle', got?.stagedApp, stagedApp);

console.log('== Still adopted when the same version is re-offered ==');
got = await installer.readStagedUpdate(appPath, { version: '9.9.9', bundleId: BUNDLE_ID });
check('adopted for matching version', got?.version, '9.9.9');

console.log('== A marker for a DIFFERENT version is not reused ==');
got = await installer.readStagedUpdate(appPath, { version: '9.9.10', bundleId: BUNDLE_ID });
check('rejected', got, 'null');

console.log('== A marker for a different application is not reused ==');
got = await installer.readStagedUpdate(appPath, { bundleId: 'com.someone.else' });
check('rejected', got, 'null');

console.log('== A marker whose staged bundle has vanished is not reused ==');
stage(good);
fs.rmSync(stagedApp, { recursive: true, force: true });
got = await installer.readStagedUpdate(appPath, { bundleId: BUNDLE_ID });
check('rejected (bundle gone)', got, 'null');

console.log('== A marker whose swap script has vanished is not reused ==');
stage(good);
fs.rmSync(scriptPath, { force: true });
got = await installer.readStagedUpdate(appPath, { bundleId: BUNDLE_ID });
check('rejected (script gone)', got, 'null');

console.log('== No staging directory at all ==');
fs.rmSync(stagingDir, { recursive: true, force: true });
got = await installer.readStagedUpdate(appPath, { bundleId: BUNDLE_ID });
check('rejected (nothing staged)', got, 'null');

console.log('== Corrupt marker does not throw ==');
fs.mkdirSync(stagingDir, { recursive: true });
fs.writeFileSync(path.join(stagingDir, 'staged.json'), '{not json');
got = await installer.readStagedUpdate(appPath, { bundleId: BUNDLE_ID });
check('rejected (corrupt)', got, 'null');

console.log('== cleanStagingDir removes the folder ==');
stage(good);
await installer.cleanStagingDir(appPath);
check('staging removed', fs.existsSync(stagingDir), 'false');

console.log(`\npersistence: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
