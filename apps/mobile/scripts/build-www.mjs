import { execSync } from 'node:child_process';
import { cpSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const mobile = path.resolve(here, '..');
const web = path.resolve(mobile, '..', 'web');
const dist = path.join(web, 'dist');
const www = path.join(mobile, 'www');
const apiBase = process.env.CAPACITOR_API_BASE || 'https://85.192.37.58.nip.io:8443/api/v1';

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
