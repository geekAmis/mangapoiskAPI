import { existsSync } from 'node:fs';
import { preview } from 'vite';
import { chromium } from 'playwright-core';

const LEGAL_PATHS = ['/terms', '/privacy', '/dmca', '/contacts', '/age'];
const VIEWPORT = { width: 390, height: 844 };
const PORT = Number(process.env.QA_PORT ?? 4174);

const browserCandidates = [
  process.env.QA_BROWSER_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);
const executablePath = browserCandidates.find((candidate) => existsSync(candidate));

if (!executablePath) {
  console.log(
    'legal-overflow: skipped (set QA_BROWSER_PATH to Chrome/Edge/Chromium for this QA check)',
  );
  process.exit(0);
}

const server = await preview({
  preview: { port: PORT, strictPort: true },
  logLevel: 'silent',
});
if (!server.httpServer.listening) {
  await new Promise((resolve) => server.httpServer.once('listening', resolve));
}
const baseUrl = (server.resolvedUrls?.local?.[0] ?? `http://localhost:${PORT}`).replace(
  /\/$/,
  '',
);

const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: VIEWPORT, locale: 'ru-RU' });
let failed = false;

try {
  // The legal pages do not need ad creatives; stop the Yandex request from
  // slowing the check or touching the real network.
  await page.route('https://yandex.ru/**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/javascript', body: '' }),
  );

  for (const path of LEGAL_PATHS) {
    const response = await page.goto(`${baseUrl}${path}`, {
      waitUntil: 'networkidle',
    });
    await page.waitForSelector('.legal-doc');

    const metrics = await page.evaluate(() => {
      const doc = document.documentElement;
      const wrappers = [...document.querySelectorAll('.legal-table-wrap')].map(
        (wrapper) => ({
          clientWidth: wrapper.clientWidth,
          scrollWidth: wrapper.scrollWidth,
        }),
      );
      return {
        innerWidth: window.innerWidth,
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        tableWrappers: wrappers,
      };
    });

    const ok =
      response?.ok() &&
      metrics.scrollWidth === metrics.innerWidth &&
      metrics.bodyScrollWidth <= metrics.innerWidth;
    if (!ok) failed = true;

    let tableWrapper = '';
    if (path === '/privacy') {
      const wrapper = metrics.tableWrappers[0];
      if (!wrapper || wrapper.scrollWidth <= wrapper.clientWidth) {
        failed = true;
        console.error(
          `legal-overflow: privacy table should scroll inside its wrapper: ${JSON.stringify(wrapper)}`,
        );
      } else {
        tableWrapper = ` tableClientWidth=${wrapper.clientWidth} tableScrollWidth=${wrapper.scrollWidth}`;
      }
    }

    console.log(
      `${ok ? 'OK' : 'FAIL'} ${path} ` +
        `innerWidth=${metrics.innerWidth} scrollWidth=${metrics.scrollWidth} ` +
        `bodyScrollWidth=${metrics.bodyScrollWidth}${tableWrapper}`,
    );

    if (process.env.QA_SCREENSHOT_DIR) {
      const safeName = path.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '');
      await page.screenshot({
        path: `${process.env.QA_SCREENSHOT_DIR}/legal-${safeName}-390.png`,
        fullPage: true,
      });
    }
  }
} finally {
  await browser.close();
  await server.close();
}

if (failed) process.exit(1);
