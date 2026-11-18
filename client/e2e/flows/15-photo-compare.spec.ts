import { test, expect, folderUrl } from '../fixtures';

// Compare from the selection bar: two cards open the side-by-side workspace with the first as
// reference and the second as candidate; promoting the candidate swaps the roles. A visit to the
// workspace without a selection goes back to the gallery.
test('two selected photos open the compare workspace and the candidate can become the reference', async ({ page }) => {
  await test.step('1. Without a comparison in progress, /photo-compare returns to the gallery', async () => {
    await page.goto('/photo-compare');
    await expect(page).not.toHaveURL(/photo-compare/);
  });

  await test.step('2. Select two cards and press Compare', async () => {
    await page.goto(folderUrl('filter'));
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await page.getByRole('button', { name: 'IMG_0402.jpg', exact: true }).click();
    await page.getByRole('button', { name: 'IMG_0403.jpg', exact: true }).click();
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    await expect(page).toHaveURL(/\/photo-compare/);
    await expect(page.getByRole('heading', { name: 'Comparing 2 photos', level: 1 })).toBeVisible();
  });

  await test.step('3. The first photo is the Reference and the second the Candidate', async () => {
    await expect(page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Reference' }) }))
      .toContainText('IMG_0402.jpg');
    await expect(page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Candidate' }) }))
      .toContainText('IMG_0403.jpg');
  });

  await test.step('4. Use as reference swaps the roles', async () => {
    await page.getByRole('button', { name: 'Use IMG_0403.jpg as reference' }).click();
    await expect(page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Reference' }) }))
      .toContainText('IMG_0403.jpg');
    await expect(page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Candidate' }) }))
      .toContainText('IMG_0402.jpg');
  });

  await test.step('5. Back returns to the gallery', async () => {
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page).not.toHaveURL(/photo-compare/);
  });
});
