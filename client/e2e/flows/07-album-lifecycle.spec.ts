import { test, expect, libraryPath, editionToken } from '../fixtures';

// An album made through the API (edition mode) shows on /albums with its photo count, opens to its
// photo, and disappears from the page once deleted.
test('an album lists on /albums, opens to its photo and vanishes when deleted', async ({ page }) => {
  const name = 'E2E album lifecycle';
  const token = await editionToken(page);
  const headers = { Authorization: `Bearer ${token}` };
  let albumId = 0;

  await test.step('1. Create the album and add a photo (edition mode)', async () => {
    const created = await page.request.post('/api/albums', { headers, data: { name, description: '', is_smart: false } });
    expect(created.ok(), `create: ${created.status()} ${await created.text()}`).toBeTruthy();
    albumId = (await created.json()).id as number;
    const added = await page.request.post(`/api/albums/${albumId}/photos`, {
      headers, data: { photo_paths: [libraryPath('review', 'IMG_0301.jpg')] },
    });
    expect(added.ok(), `add: ${added.status()} ${await added.text()}`).toBeTruthy();
    expect((await added.json()).added).toBe(1);
  });

  try {
    await test.step('2. /albums lists it', async () => {
      await page.goto('/albums');
      await expect(page.getByText(name, { exact: true })).toBeVisible();
    });

    await test.step('3. Opening it shows its photo', async () => {
      await page.goto(`/album/${albumId}`);
      await expect(page.getByRole('button', { name: 'IMG_0301.jpg', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toHaveCount(0);
    });
  } finally {
    await test.step('4. Delete it: it leaves /albums and its photo stays in the library', async () => {
      const deleted = await page.request.delete(`/api/albums/${albumId}`, { headers });
      expect(deleted.ok(), `delete: ${deleted.status()}`).toBeTruthy();
      await page.goto('/albums');
      await expect(page.getByText(name, { exact: true })).toHaveCount(0);
      await page.goto('/');
      await expect(page.getByRole('button', { name: 'IMG_0301.jpg', exact: true })).toBeVisible();
    });
  }
});
