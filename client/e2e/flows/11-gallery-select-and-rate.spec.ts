import { test, expect, seedTool, unlockEdition, cardNames, folderUrl, libraryPath } from '../fixtures';

// Batch review from the selection bar: two cards selected, Review > Favorite and Review > Rate 4
// are applied to both, and the gallery's favourites filter and the photo page read them back.
test('Review in the selection bar favourites and rates every selected photo', async ({ page }) => {
  seedTool('reset', 'filter');
  await unlockEdition(page);
  const picked = ['IMG_0402.jpg', 'IMG_0403.jpg'];

  const selectBoth = async () => {
    await page.goto(folderUrl('filter'));
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    for (const name of picked) await page.getByRole('button', { name, exact: true }).click();
    await expect(page.getByRole('region', { name: '2 selected' })).toBeVisible();
  };
  const reviewWith = async (item: string) => {
    const rating = item.startsWith('Rate');
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Review', exact: true }).click();
    const answer = page.waitForResponse((r) => r.request().method() === 'POST' && /\/api\/photos\/batch_(rating|favorite)/.test(r.url()));
    await page.getByRole('menuitem', { name: item, exact: true }).click();
    // A rating asks to confirm in a dialog that names the captured photos; a favourite applies at once.
    if (rating) {
      await expect(page.getByRole('dialog', { name: 'Edit personal rating' })).toContainText('2 photos');
      await page.getByRole('button', { name: 'Apply' }).click();
    }
    expect((await answer).ok()).toBeTruthy();
  };

  await test.step('1. Select two cards and Review > Favorite: the server accepts it', async () => {
    await selectBoth();
    await reviewWith('Favorite');
  });

  await test.step('2. Select them again and Review > Rate 4', async () => {
    await selectBoth();
    await reviewWith('Rate 4');
  });

  await test.step('3. The favourites filter lists exactly the two', async () => {
    await page.goto(folderUrl('filter', '&favorites_only=true'));
    await expect.poll(() => cardNames(page)).toEqual(picked);
  });

  await test.step('4. The photo page shows four stars on a rated photo', async () => {
    await page.goto(`/photo?path=${encodeURIComponent(libraryPath('filter', 'IMG_0403.jpg'))}`);
    await expect(page.getByRole('button', { name: 'Set rating: 4' })).toHaveAttribute('aria-pressed', 'true');
  });
});
