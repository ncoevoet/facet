import { test, expect, libraryPath } from '../fixtures';

// An AI edit that outscores its original leads the burst, and the original's photo page offers it
// in the burst strip, labelled for screen readers. (#444 / #445)
test('the burst strip offers the AI edit beside its original', async ({ page }) => {
  await test.step('1. The gallery shows the burst once, as the AI edit', async () => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'IMG_0001_agy_1.jpg', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'IMG_0001.jpg', exact: true })).toHaveCount(0);
  });

  await test.step("2. The original's strip lists the edit as an AI edit", async () => {
    await page.goto('/photo?path=' + encodeURIComponent(libraryPath('burst', 'IMG_0001.jpg')));
    await expect(page.getByRole('button', { name: 'Frame 3 of 3, AI edit' })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Frame [12] of 3$/ })).toHaveCount(2);
  });

  await test.step('3. Choosing the edit in the strip opens the edit', async () => {
    await page.getByRole('button', { name: 'Frame 3 of 3, AI edit' }).click();
    await expect(page).toHaveURL(/IMG_0001_agy_1\.jpg/);
  });
});
