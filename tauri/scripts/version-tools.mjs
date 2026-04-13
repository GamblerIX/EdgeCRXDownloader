import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const packageJsonPath = path.join(rootDir, 'package.json');
const cargoTomlPath = path.join(rootDir, 'src-tauri', 'Cargo.toml');

function readPackageVersion() {
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

  if (typeof packageJson.version !== 'string' || packageJson.version.length === 0) {
    throw new Error('package.json is missing a valid version field.');
  }

  return packageJson.version;
}

function syncCargoVersion(version) {
  const cargoToml = fs.readFileSync(cargoTomlPath, 'utf8');
  const lines = cargoToml.split(/\r?\n/);
  const packageHeaderIndex = lines.findIndex((line) => line.trim() === '[package]');

  if (packageHeaderIndex === -1) {
    throw new Error('Cargo.toml is missing a [package] section.');
  }

  const packageVersionIndex = lines.findIndex(
    (line, index) => index > packageHeaderIndex && line.startsWith('version = '),
  );

  if (packageVersionIndex === -1) {
    throw new Error('Cargo.toml is missing a package version entry.');
  }

  const nextSectionIndex = lines.findIndex(
    (line, index) => index > packageHeaderIndex && line.startsWith('['),
  );

  if (nextSectionIndex !== -1 && packageVersionIndex > nextSectionIndex) {
    throw new Error('Cargo.toml package version entry is not inside the [package] section.');
  }

  const nextVersionLine = `version = "${version}"`;
  const changed = lines[packageVersionIndex] !== nextVersionLine;
  lines[packageVersionIndex] = nextVersionLine;
  fs.writeFileSync(cargoTomlPath, `${lines.join('\n')}\n`);

  return changed;
}

const command = process.argv[2];
const packageVersion = readPackageVersion();

switch (command) {
  case 'print':
    process.stdout.write(packageVersion);
    break;
  case 'sync': {
    const changed = syncCargoVersion(packageVersion);
    process.stdout.write(
      changed
        ? `Synced src-tauri/Cargo.toml to ${packageVersion}\n`
        : `src-tauri/Cargo.toml already matches ${packageVersion}\n`,
    );
    break;
  }
  default:
    throw new Error('Usage: node scripts/version-tools.mjs <print|sync>');
}
