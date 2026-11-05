import { test, expect, libraryPath, seedTool, centrePixel } from '../fixtures';

// Deleting an AI edit frees its number, so the next import reuses the path. The browser (service
// worker + HTTP cache) must still show the NEW picture. Found by hand as B22: the card kept the
// deleted edit's thumbnail under the new edit's name.
test('an edit imported under a deleted edit’s name shows the new picture', async ({ page }) => {
  const edit = libraryPath('reuse', 'IMG_0100_agy_1.jpg');
  const card = 'role=button[name="IMG_0100_agy_1.jpg"] >> img';

  await test.step('1. The gallery card shows the red edit (and caches it)', async () => {
    await page.goto('/');
    await expect(page.locator(card)).toBeVisible();
    const [r, g, b] = await centrePixel(page, card);
    expect(r > 180 && g < 90 && b < 90, `expected red, got ${r},${g},${b}`).toBeTruthy();
  });

  await test.step('2. Delete it and import a blue edit under the same name, then scan', async () => {
    seedTool('reimport', edit, '#1c7ed6');
  });

  await test.step('3. After a reload the same card shows blue, not the cached red', async () => {
    await page.reload();
    await expect(page.locator(card)).toBeVisible();
    const [r, g, b] = await centrePixel(page, card);
    expect(b > 150 && r < 90, `expected blue, got ${r},${g},${b}`).toBeTruthy();
  });
});
