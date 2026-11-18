import { test, expect } from '../fixtures';

// /map draws one marker per located cluster. The seed has photos in Paris and New York and one
// without GPS: two markers, each holding one photo, and a marker opens a popup that closes again.
test('the map shows a marker per located photo and opens its popup', async ({ page }) => {
  await test.step('1. Two markers, each counting one photo', async () => {
    await page.goto('/map');
    await expect(page.getByRole('heading', { name: 'Map' })).toBeVisible();
    const markers = page.getByRole('tooltip');
    await expect(markers).toHaveCount(2);
    await expect(markers.first()).toHaveText('1');
    await expect(markers.last()).toHaveText('1');
  });

  await test.step('2. A marker opens a popup naming its photos', async () => {
    await page.getByRole('tooltip').first().click({ force: true });
    await expect(page.getByRole('img', { name: '1 photos' })).toBeVisible();
  });

  await test.step('3. The popup closes', async () => {
    await page.getByRole('button', { name: 'Close popup' }).click();
    await expect(page.getByRole('img', { name: '1 photos' })).toHaveCount(0);
  });
});
