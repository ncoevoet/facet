import { test, expect, libraryPath, editionToken, expectFailedLoad } from '../fixtures';

// A shared album is public: its link shows the album's photos with no login, a wrong token is
// refused, and once the share is revoked the old link stops working.
test('a shared album opens by link without login and stops once unshared', async ({ page }) => {
  const name = 'E2E shared album';
  const headers = { Authorization: `Bearer ${await editionToken(page)}` };
  let albumId = 0;
  let link = '';
  expectFailedLoad(page, /^403 GET .*\/api\/shared\/album\//);

  try {
    await test.step('1. Create an album with one photo and share it', async () => {
      const created = await page.request.post('/api/albums', { headers, data: { name, description: '', is_smart: false } });
      albumId = (await created.json()).id as number;
      await page.request.post(`/api/albums/${albumId}/photos`, {
        headers, data: { photo_paths: [libraryPath('review', 'IMG_0301.jpg')] },
      });
      const shared = await page.request.post(`/api/albums/${albumId}/share`, { headers });
      expect(shared.ok()).toBeTruthy();
      link = (await shared.json()).share_url as string;
      expect(link).toContain(`/shared/album/${albumId}?token=`);
    });

    await test.step('2. The link shows the album and its photo, with no login', async () => {
      await page.goto(link);
      await expect(page.getByRole('heading', { name })).toBeVisible();
      await expect(page.getByRole('button', { name: 'IMG_0301.jpg', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toHaveCount(0);
    });

    await test.step('3. A wrong token is refused', async () => {
      const refused = await page.request.get(`/api/shared/album/${albumId}?token=nope`);
      expect(refused.status()).toBe(403);
    });

    await test.step('4. After unsharing, the old link no longer shows the photo', async () => {
      expect((await page.request.delete(`/api/albums/${albumId}/share`, { headers })).ok()).toBeTruthy();
      await page.goto(link);
      await expect(page.getByRole('button', { name: 'IMG_0301.jpg', exact: true })).toHaveCount(0);
      expect((await page.request.get(link.replace('/shared/album/', '/api/shared/album/'))).status()).toBe(403);
    });
  } finally {
    if (albumId) await page.request.delete(`/api/albums/${albumId}`, { headers });
  }
});
