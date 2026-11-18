import fs from 'node:fs';
import path from 'node:path';
import { test, expect, libraryPath, editionToken, unlockEdition, WORK } from '../fixtures';

// Export portfolio writes an album as a static website into a chosen folder: Export waits for a
// target folder, then the folder holds an index page and the album's photo.
test('an album exports as a static portfolio site', async ({ page }) => {
  const name = 'E2E portfolio';
  const target = path.join(WORK, 'exports', 'portfolio');
  fs.rmSync(target, { recursive: true, force: true });
  await unlockEdition(page);
  const headers = { Authorization: `Bearer ${await editionToken(page)}` };
  const created = await page.request.post('/api/albums', { headers, data: { name, description: '', is_smart: false } });
  const albumId = (await created.json()).id as number;

  try {
    await page.request.post(`/api/albums/${albumId}/photos`, {
      headers, data: { photo_paths: [libraryPath('review', 'IMG_0301.jpg')] },
    });

    await test.step('1. Export portfolio opens from the album card and waits for a folder', async () => {
      await page.goto('/albums');
      await page.getByRole('button', { name: `More: ${name}` }).click();
      await page.getByRole('menuitem', { name: 'Export portfolio' }).click();
      const dialog = page.getByRole('dialog', { name: 'Export portfolio' });
      await expect(dialog.getByRole('textbox', { name: 'Gallery title' })).toHaveValue(name);
      await expect(dialog.getByRole('button', { name: 'Export' })).toBeDisabled();
      await dialog.getByRole('textbox', { name: 'Target folder' }).fill(target);
      await expect(dialog.getByRole('button', { name: 'Export' })).toBeEnabled();
    });

    await test.step('2. Exporting writes the site into the folder', async () => {
      const answer = page.waitForResponse((r) => r.url().includes('/export') && r.request().method() === 'POST');
      await page.getByRole('dialog', { name: 'Export portfolio' }).getByRole('button', { name: 'Export' }).click();
      expect((await answer).ok()).toBeTruthy();
      await expect.poll(() => fs.existsSync(path.join(target, 'index.html'))).toBeTruthy();
      expect(fs.readFileSync(path.join(target, 'index.html'), 'utf8')).toContain(name);
    });
  } finally {
    await page.request.delete(`/api/albums/${albumId}`, { headers });
    fs.rmSync(target, { recursive: true, force: true });
  }
});
