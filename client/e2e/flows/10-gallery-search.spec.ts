import { test, expect, cardNames, folderUrl } from '../fixtures';

// Free-text search over captions: a word from one caption narrows the grid to that photo, the
// search survives a reload, and clearing it brings the folder back.
test('searching a caption word narrows the gallery and survives a reload', async ({ page }) => {
  const box = page.getByRole('searchbox', { name: 'Search filename, caption...' });

  await test.step('1. The folder lists its five photos', async () => {
    await page.goto(folderUrl('filter'));
    await expect.poll(() => cardNames(page)).toHaveLength(5);
  });

  await test.step('2. A caption word narrows the grid to the one photo', async () => {
    await box.fill('kayak');
    await box.press('Enter');
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0400.jpg']);
  });

  await test.step('3. A reload keeps the search and the result', async () => {
    await page.reload();
    await expect(box).toHaveValue('kayak');
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0400.jpg']);
  });

  await test.step('4. A word no photo carries lists nothing', async () => {
    await box.fill('zeppelin');
    await box.press('Enter');
    await expect.poll(() => cardNames(page)).toEqual([]);
  });

  await test.step('5. Clearing the search restores the folder', async () => {
    await box.fill('');
    await box.press('Enter');
    await expect.poll(() => cardNames(page)).toHaveLength(5);
  });
});
