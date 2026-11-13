import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const WEB_ROOT = process.cwd();
const REPO_ROOT = resolve(WEB_ROOT, '../..');
const INDEX_HTML = readFileSync(resolve(WEB_ROOT, 'index.html'), 'utf8');
const ADS_TXT = readFileSync(resolve(WEB_ROOT, 'public/ads.txt'), 'utf8');
const NGINX = readFileSync(resolve(REPO_ROOT, 'infra/nginx/default.conf'), 'utf8');

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

describe('Yandex RTB infrastructure', () => {
  it('adds the loader exactly once in index.html', () => {
    const queue = INDEX_HTML.match(/window\.yaContextCb=window\.yaContextCb\|\|\[\]/g) ?? [];
    const loader = INDEX_HTML.match(
      /https:\/\/yandex\.ru\/ads\/system\/context\.js/g,
    ) ?? [];
    expect(queue).toHaveLength(1);
    expect(loader).toHaveLength(1);
    expect(INDEX_HTML).toContain('<script src="https://yandex.ru/ads/system/context.js" async></script>');
  });

  it('ships the production ads.txt from public/', () => {
    expect(ADS_TXT.trimEnd().split(/\r?\n/)).toEqual([
      'google.com, pub-5533854580432370, RESELLER, f08c47fec0942fa0',
      'improvedigital.com, 2031, RESELLER',
      'uis.mobfox.com, 165, RESELLER',
      'hyperad.tech, 215, RESELLER',
      'betweendigital.com, 43554, RESELLER',
      'yandex.com, 334843219, DIRECT',
      'Contextweb.com, 562899, RESELLER, 89ff185a4c4e857c',
      'hyperad.tech, 150, RESELLER',
      'yandex.com, 20411736, DIRECT',
    ]);
  });

  it('allows Yandex in CSP without weakening frame-ancestors/object-src', () => {
    const scriptSrc = directive('script-src');
    expect(scriptSrc).toContain('https://yandex.ru');
    expect(scriptSrc).toContain('https://an.yandex.ru');
    expect(scriptSrc).toContain('https://yastatic.net');

    const frameSrc = directive('frame-src');
    expect(frameSrc).toContain('https://yandex.ru');
    expect(frameSrc).toContain('https://an.yandex.ru');

    expect(directive('connect-src')).toContain('https:');
    expect(directive('img-src')).toContain('https:');
    expect(directive('object-src')).toContain("'none'");
    expect(directive('frame-ancestors')).toContain("'self'");
  });
});
