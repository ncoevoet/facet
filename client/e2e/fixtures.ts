import { execFileSync } from 'node:child_process';
import * as path from 'node:path';
import { test as base, expect, type Page } from '@playwright/test';
import { EDITION_PASSWORD, PYTHON } from './env';

export const WORK = path.resolve(__dirname, '.work');

/** Absolute path of a seeded photo, spelled the way the server stored it. */
export function libraryPath(folder: string, name: string): string {
  return path.join(WORK, 'library', folder, name);
}

/** Run a seed_library.py subcommand against the running server's database. */
export function seedTool(...args: string[]): void {
  // No cwd: a relative FACET_E2E_PYTHON resolves from client/, as for the web server.
  execFileSync(PYTHON, [path.join(__dirname, 'seed_library.py'), ...args], { stdio: 'pipe' });
}

/** Log in to edition mode the way the client does, and return the bearer token. */
export async function editionToken(page: Page): Promise<string> {
  const res = await page.request.post('/api/auth/edition/login', { data: { password: EDITION_PASSWORD } });
  expect(res.ok(), `edition login: ${res.status()}`).toBeTruthy();
  return (await res.json()).access_token as string;
}

/** The RGB of the middle pixel of a rendered <img>, read through a canvas. */
export async function centrePixel(page: Page, selector: string): Promise<[number, number, number]> {
  return page.locator(selector).first().evaluate(async (img: HTMLImageElement) => {
    if (!img.complete) await new Promise((r) => img.addEventListener('load', r, { once: true }));
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(Math.floor(img.naturalWidth / 2), Math.floor(img.naturalHeight / 2), 1, 1).data;
    return [d[0], d[1], d[2]] as [number, number, number];
  });
}

/** Every flow fails on a page error, a console error or a 5xx answer, even if the screen looks fine. */
export const test = base.extend<{ gate: void }>({
  gate: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
      let failedLoad = false;
      page.on('console', (msg) => {
        if (msg.type() !== 'error') return;
        problems.push(`console.error: ${msg.text()}`);
        if (msg.text().startsWith('Failed to load resource')) failedLoad = true;
      });
      // A failed load logs only "Failed to load resource"; keep the URLs so the report names them.
      const failed: string[] = [];
      page.on('response', (res) => {
        const line = `${res.status()} ${res.request().method()} ${decodeURIComponent(res.url())}`;
        if (res.status() >= 500) problems.push(line);
        else if (res.status() >= 400) failed.push(line);
      });
      await use();
      if (failedLoad && failed.length) problems.push(`4xx responses: ${failed.join(' ; ')}`);
      expect(problems, 'errors seen during the flow').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
