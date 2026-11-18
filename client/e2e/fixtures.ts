import * as fs from 'node:fs';
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

let cachedToken: string | null = null;
// A failed test restarts the worker and with it this module, so the token also lives in a file the
// seeding rewrites on every run; otherwise each restart would spend another of the 5 logins a minute.
const TOKEN_FILE = path.join(WORK, 'edition-token.txt');

/**
 * Log in to edition mode the way the client does, and return the bearer token. The login route
 * allows 5 attempts a minute per address, so the token is fetched once per run and reused.
 */
export async function editionToken(page: Page): Promise<string> {
  if (!cachedToken && fs.existsSync(TOKEN_FILE)) cachedToken = fs.readFileSync(TOKEN_FILE, 'utf8');
  if (cachedToken) return cachedToken;
  const res = await page.request.post('/api/auth/edition/login', { data: { password: EDITION_PASSWORD } });
  expect(res.ok(), `edition login: ${res.status()}`).toBeTruthy();
  cachedToken = (await res.json()).access_token as string;
  fs.writeFileSync(TOKEN_FILE, cachedToken);
  return cachedToken;
}

/** Open the page already unlocked for edition mode, without spending a login attempt on the UI. */
export async function unlockEdition(page: Page): Promise<void> {
  const token = await editionToken(page);
  await page.addInitScript((t) => localStorage.setItem('facet_token', t), token);
}

/** File names of the photo cards on screen, in display order. */
export async function cardNames(page: Page): Promise<string[]> {
  return page.getByRole('gridcell').evaluateAll((cells) =>
    cells.map((c) => c.querySelector('[role="button"]')?.getAttribute('aria-label') ?? ''));
}

/** The gallery scoped to one seeded folder, with every burst member visible. */
export function folderUrl(folder: string, extra = ''): string {
  return `/?hide_bursts=false&path_prefix=${encodeURIComponent(path.join(WORK, 'library', folder))}${extra}`;
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

const expectedFailures = new WeakMap<Page, RegExp[]>();

/**
 * Declare that a flow deliberately provokes a 4xx answer (a wrong password, say). The browser logs
 * it as a console error, which the gate below would fail on: only answers matching `pattern`
 * ("METHOD status url") are forgiven, any other 4xx or console error still fails the flow.
 */
export function expectFailedLoad(page: Page, pattern: RegExp): void {
  expectedFailures.set(page, [...(expectedFailures.get(page) ?? []), pattern]);
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
      const allowed = expectedFailures.get(page) ?? [];
      const unexpected = failed.filter((line) => !allowed.some((re) => re.test(line)));
      if (failedLoad && failed.length && !unexpected.length) {
        // Every 4xx was declared: drop the matching "Failed to load resource" console errors.
        for (let i = problems.length - 1; i >= 0; i--) {
          if (problems[i].startsWith('console.error: Failed to load resource')) problems.splice(i, 1);
        }
      } else if (failedLoad && failed.length) problems.push(`4xx responses: ${failed.join(' ; ')}`);
      expect(problems, 'errors seen during the flow').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
