import { test, expect, libraryPath, editionToken } from '../fixtures';

// Deleting the AI edit that leads its burst must hand the lead to the best remaining frame, or Hide
// bursts hides the whole burst. Found while reproducing B22, as B23.
test('deleting the AI edit that leads its burst keeps the burst in the gallery', async ({ page }) => {
  await test.step('1. The burst shows as its leading AI edit', async () => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'IMG_0200_agy_1.jpg', exact: true })).toBeVisible();
  });

  await test.step('2. Delete the leading edit (edition mode)', async () => {
    const token = await editionToken(page);
    const res = await page.request.post('/api/photo/delete', {
      headers: { Authorization: `Bearer ${token}` },
      data: { paths: [libraryPath('lead', 'IMG_0200_agy_1.jpg')], dry_run: false },
    });
    expect(res.ok(), `delete: ${res.status()} ${await res.text()}`).toBeTruthy();
    expect((await res.json()).deleted).toHaveLength(1);
  });

  await test.step('3. The burst is still in the gallery, led by its best remaining frame', async () => {
    await page.reload();
    await expect(page.getByRole('button', { name: 'IMG_0200_agy_1.jpg', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'IMG_0200.jpg', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'IMG_0201.jpg', exact: true })).toHaveCount(0);
  });
});
