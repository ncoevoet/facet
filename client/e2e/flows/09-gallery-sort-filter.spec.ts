import { test, expect, cardNames, folderUrl } from '../fixtures';

const BY_SCORE = ['IMG_0400.jpg', 'IMG_0401.jpg', 'IMG_0402.jpg', 'IMG_0403.jpg', 'IMG_0404.jpg'];

// Sorting and the score and camera filters on the five-photo `filter` folder: the order follows the
// score, flips on demand, and each filter narrows the grid to the photos that match and back.
test('the gallery sorts by score and narrows by score range and camera', async ({ page }) => {
  await test.step('1. Scoped to the folder, the cards run from the highest score down', async () => {
    await page.goto(folderUrl('filter'));
    await expect(page.getByRole('status').filter({ hasText: '5 photos' })).toBeVisible();
    expect(await cardNames(page)).toEqual(BY_SCORE);
  });

  await test.step('2. Descending flips to ascending: the order reverses', async () => {
    await page.getByRole('button', { name: 'Descending', exact: true }).click();
    await expect.poll(() => cardNames(page)).toEqual([...BY_SCORE].reverse());
  });

  await test.step('3. A camera filter keeps only that camera\'s photos', async () => {
    await page.getByRole('button', { name: /^Filters/ }).click();
    await page.getByRole('tab', { name: 'Source' }).click();
    await page.getByRole('combobox', { name: 'Camera' }).click();
    await page.getByRole('option', { name: /E2E Alpha/ }).click();
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0401.jpg', 'IMG_0400.jpg']);
    await expect(page.getByRole('group', { name: 'Active criteria' })).toContainText('E2E Alpha');
  });

  await test.step('4. Removing the camera chip restores the folder', async () => {
    await page.getByRole('button', { name: 'Remove Camera' }).click();
    await expect.poll(() => cardNames(page)).toHaveLength(5);
  });

  await test.step('5. A minimum score drops the photos below it', async () => {
    await page.getByRole('tab', { name: 'Quality' }).click();
    await page.getByRole('button', { name: 'Quality', exact: true }).click();
    const min = page.getByRole('slider', { name: 'Score Range min' });
    await min.focus();
    // One key at a time: each step re-queries the gallery, and a burst of keys is partly dropped.
    for (let value = 2.5; value <= 6; value += 0.5) {
      await min.press('ArrowRight');
      await expect(min).toHaveValue(String(value));
    }
    await expect(page).toHaveURL(/min_score=6/);
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0401.jpg', 'IMG_0400.jpg']);
  });
});
