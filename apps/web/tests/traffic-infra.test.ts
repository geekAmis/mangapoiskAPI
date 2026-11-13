import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const WEB_ROOT = process.cwd();
const REPO_ROOT = resolve(WEB_ROOT, '../..');
const INDEX_HTML = readFileSync(resolve(WEB_ROOT, 'index.html'), 'utf8');
const NGINX = readFileSync(resolve(REPO_ROOT, 'infra/nginx/default.conf'), 'utf8');
const ROOT_ENV = readFileSync(resolve(REPO_ROOT, '.env.example'), 'utf8');
const WEB_ENV = readFileSync(resolve(WEB_ROOT, '.env.example'), 'utf8');

function directive(name: string): string {
  const match = NGINX.match(/Content-Security-Policy\s+"([^"]+)"/);
  expect(match).toBeTruthy();
  const found = (match?.[1] ?? '')
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name} `));
  expect(found, `CSP directive ${name}`).toBeTruthy();
  return found ?? '';
}

describe('Yandex Metrika infrastructure (#85)', () => {
  it('does not hardcode a counter or loader in index.html', () => {
    expect(INDEX_HTML).not.toContain('mc.yandex.ru');
    expect(INDEX_HTML).not.toContain('metrika/tag.js');
  });

  it('allows mc.yandex.ru in script/connect/img and yastatic fonts in CSP', () => {
    expect(directive('script-src')).toContain('https://mc.yandex.ru');
    expect(directive('connect-src')).toContain('https://mc.yandex.ru');
    expect(directive('img-src')).toContain('https://mc.yandex.ru');
    expect(directive('font-src')).toContain('https://yastatic.net');
    expect(directive('object-src')).toContain("'none'");
    expect(directive('frame-ancestors')).toContain("'self'");
  });

  it('documents the build-time counter id without a real value', () => {
    expect(ROOT_ENV).toMatch(/^YANDEX_METRIKA_ID=\s*$/m);
    expect(WEB_ENV).toContain('VITE_YANDEX_METRIKA_ID');
  });
});
