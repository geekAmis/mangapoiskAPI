import { execSync } from 'node:child_process';
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const mobile = path.resolve(here, '..');
const web = path.resolve(mobile, '..', 'web');
const dist = path.join(web, 'dist');
const www = path.join(mobile, 'www');
const defaultApiBase = 'https://85.192.37.58.nip.io:8443/api/v1';
const apiBase = (process.env.CAPACITOR_API_BASE || defaultApiBase).trim();
const localDevApi = /^http:\/\/(?:localhost|127\.0\.0\.1|10\.0\.2\.2)(?::\d+)?(?:\/|$)/i;

// Production bundles must never contain a plain-HTTP API fallback. Local
// development servers are still allowed so `adb reverse` workflows keep
// working, but any other http:// URL is a hard build error.
if (!apiBase.startsWith('https://') && !localDevApi.test(apiBase)) {
  console.error(
    `Refusing to build: CAPACITOR_API_BASE must be HTTPS or a localhost dev URL, got ${apiBase}`,
  );
  console.error('Set CAPACITOR_API_BASE=https://<host>/api/v1 for release builds.');
  process.exit(1);
}

console.log(`Building web with VITE_API_BASE=${apiBase}`);
execSync('npm run build', {
  cwd: web,
  stdio: 'inherit',
  env: { ...process.env, VITE_API_BASE: apiBase },
});

rmSync(www, { recursive: true, force: true });
mkdirSync(www, { recursive: true });
if (process.platform === 'win32') {
  // fs.cpSync can hit EIO on Windows/antivirus; xcopy is boring and reliable.
  execSync(`xcopy "${dist}" "${www}" /E /I /Y /Q`, { stdio: 'inherit' });
} else {
  cpSync(dist, www, { recursive: true });
}
console.log(`Copied ${dist} -> ${www}`);

// Fail the build if a stale HTTP API base survived in the packaged web assets.
const legacyHttp = /http:\/\/85\.192\.37\.58(?::8088)?(?:\/|\b)/i;
const offenders = [];
for (const entry of readdirSync(www, { recursive: true, withFileTypes: true })) {
  if (!entry.isFile() || !/\.(?:js|json|html|webmanifest)$/i.test(entry.name)) continue;
  const file = path.join(entry.parentPath ?? entry.path, entry.name);
  if (legacyHttp.test(readFileSync(file, 'utf8'))) {
    offenders.push(path.relative(www, file));
  }
}
if (offenders.length > 0) {
  console.error(`Refusing to package HTTP API fallback in: ${offenders.join(', ')}`);
  process.exit(1);
}
console.log('Verified: no plain-HTTP API fallback in www/');
