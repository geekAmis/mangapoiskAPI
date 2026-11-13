import { readFileSync } from 'node:fs';

const file = new URL('../dist/ads.txt', import.meta.url);
let text = '';
try {
  text = readFileSync(file, 'utf8');
} catch {
  console.error(`ads.txt deploy check failed: ${file.pathname} is missing`);
  process.exit(1);
}

const required = [
  'yandex.com, 20411736, DIRECT',
  'yandex.com, 334843219, DIRECT',
];
const missing = required.filter((line) => !text.includes(line));
if (missing.length > 0) {
  console.error(`ads.txt deploy check failed: missing ${missing.join(', ')}`);
  process.exit(1);
}

console.log(`ads.txt deploy check OK (${text.trim().split(/\r?\n/).length} lines)`);
