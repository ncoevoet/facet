import { test, expect, cardNames } from '../fixtures';

// Drill-down navigation: the timeline's month page counts the photos of the day they were taken
// and links to them, and the Folders page filters the gallery to the folder that was clicked.
test('the timeline month and the folders page lead to the right photos', async ({ page }) => {
  await test.step('1. /timeline/2026/2 counts the five photos of 14 Feb on that day', async () => {
    await page.goto('/timeline/2026/2');
    await expect(page.getByRole('button', { name: '2026-02-14 · Photos: 5' })).toBeVisible();
    await expect(page.getByRole('button', { name: '2026-02-13 · Photos: 0' })).toBeVisible();
    await expect(page.getByRole('region', { name: '14 Feb 2026' })).toBeVisible();
  });

  await test.step('2. View day opens the gallery on that day with its five photos', async () => {
    await page.getByRole('link', { name: /^View day/ }).click();
    await expect(page).not.toHaveURL(/\/timeline/);
    // The day view orders by capture time, not by score: compare as a set.
    await expect.poll(async () => (await cardNames(page)).sort()).toEqual(
      ['IMG_0400.jpg', 'IMG_0401.jpg', 'IMG_0402.jpg', 'IMG_0403.jpg', 'IMG_0404.jpg']);
  });

  await test.step('3. /folders lists the seeded folders with their photo counts', async () => {
    await page.goto('/folders');
    await expect(page.getByRole('button', { name: 'filter filter 5 photos' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'review review 2 photos' })).toBeVisible();
  });

  await test.step('4. Filtering by a folder opens the gallery on its photos only', async () => {
    await page.getByRole('button', { name: 'Filter gallery by this folder — review' }).click();
    await expect.poll(async () => (await cardNames(page)).sort()).toEqual(['IMG_0300.jpg', 'IMG_0301.jpg']);
  });
});
