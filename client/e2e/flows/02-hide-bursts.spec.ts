import { test, expect } from '../fixtures';

// Hide bursts (on by default) folds each burst behind its lead; Show all brings every frame back.
test('Hide bursts folds a burst behind its lead and Show all brings the frames back', async ({ page }) => {
  const cards = page.getByRole('button', { name: /^IMG_\d{4}(_agy_\d+)?\.jpg$/ });

  await test.step('1. By default one card per burst', async () => {
    await page.goto('/');
    await expect(cards).toHaveCount(3);
  });

  await test.step('2. Show all lists every seeded photo', async () => {
    await page.getByRole('button', { name: 'Show all' }).click();
    await expect(cards).toHaveCount(8);
  });
});
