import { test, expect, seedTool, unlockEdition, libraryPath } from '../fixtures';

// Review edits on the photo page persist: a star rating, the favourite flag and a Keep decision
// are still set after a reload, which reads them back from the server.
test('rating, favouriting and keeping a photo survive a reload', async ({ page }) => {
  seedTool('reset', 'edit');
  await unlockEdition(page);
  const url = `/photo?path=${encodeURIComponent(libraryPath('edit', 'IMG_0600.jpg'))}`;
  const review = () => page.getByRole('region', { name: 'Review' });

  await test.step('1. The photo starts unrated, not favourite and undecided', async () => {
    await page.goto(url);
    await expect(review().getByRole('button', { name: 'Undecided' })).toHaveAttribute('aria-pressed', 'true');
    await expect(review().getByRole('button', { name: 'Favorite' })).not.toHaveAttribute('aria-pressed', 'true');
  });

  await test.step('2. Four stars, Favorite and Keep are set', async () => {
    await review().getByRole('button', { name: 'Set rating: 4' }).click();
    await review().getByRole('button', { name: 'Favorite' }).click();
    await review().getByRole('button', { name: 'Keep', exact: true }).click();
    await expect(review().getByRole('button', { name: 'Keep', exact: true })).toHaveAttribute('aria-pressed', 'true');
  });

  await test.step('3. After a reload the three values are read back', async () => {
    await page.reload();
    await expect(review().getByRole('button', { name: 'Keep', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(review().getByRole('button', { name: 'Favorite' })).toHaveAttribute('aria-pressed', 'true');
    await expect(review().getByRole('button', { name: 'Set rating: 4' })).toHaveAttribute('aria-pressed', 'true');
  });
});
