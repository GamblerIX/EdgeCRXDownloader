import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(rootDir, 'package.json'), 'utf8'));
const tauriConfig = JSON.parse(
  fs.readFileSync(path.join(rootDir, 'src-tauri', 'tauri.conf.json'), 'utf8'),
);
const cargoToml = fs.readFileSync(path.join(rootDir, 'src-tauri', 'Cargo.toml'), 'utf8');
const ciWorkflow = fs.readFileSync(
  path.join(rootDir, '.github', 'workflows', 'CI.yml'),
  'utf8',
);
const cdWorkflow = fs.readFileSync(
  path.join(rootDir, '.github', 'workflows', 'CD.yml'),
  'utf8',
);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test('tauri config reads app version from package.json', () => {
  assert.equal(tauriConfig.version, '../package.json');
});

test('cargo package version stays aligned with package.json', () => {
  assert.match(
    cargoToml,
    new RegExp(`^version = "${escapeRegExp(packageJson.version)}"$`, 'm'),
  );
});

test('CI and CD workflows reuse the shared setup action', () => {
  assert.match(ciWorkflow, /uses: \.\/\.github\/actions\/setup-project/);
  assert.match(cdWorkflow, /uses: \.\/\.github\/actions\/setup-project/);
});

test('CD workflow reads the release version from package.json instead of a placeholder', () => {
  assert.match(cdWorkflow, /id: package_version/);
  assert.match(cdWorkflow, /node scripts\/version-tools\.mjs print/);
  assert.match(cdWorkflow, /tagName: v\$\{\{ steps\.package_version\.outputs\.value \}\}/);
  assert.doesNotMatch(cdWorkflow, /__VERSION__/);
});
