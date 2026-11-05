import { test, expect } from '../fixtures';

// Hide bursts (on by default) folds each burst behind its lead; Show all brings every frame back.
test('Hide bursts folds a burst behind its lead and Show all brings the frames back', async ({ page }) => {
  // Only the read-only 'burst' folder's frames: the other flows add and delete photos in theirs.
  const cards = page.getByRole('button', { name: /^IMG_000\d(_agy_\d+)?\.jpg$/ });

  await test.step('1. By default the burst shows as one card, its lead', async () => {
    await page.goto('/');
    await expect(cards).toHaveCount(1);
  });

  await test.step('2. Show all lists all three of its frames', async () => {
    await page.getByRole('button', { name: 'Show all' }).click();
    await expect(cards).toHaveCount(3);
  });
});
