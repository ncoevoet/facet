import { test, expect, libraryPath } from '../fixtures';

// From a gallery card to the photo page and back: the card opens its own photo, the page names it
// and shows its measurements, a tab switch shows another panel, and Back returns to the gallery.
test('a gallery card opens its photo page and Back returns to the gallery', async ({ page }) => {
  await test.step('1. The gallery lists the photo', async () => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toBeVisible();
  });

  await test.step('2. A double click opens that photo, not another', async () => {
    await page.getByRole('button', { name: 'IMG_0300.jpg', exact: true }).dblclick();
    await expect(page).toHaveURL(url => url.pathname === '/photo' &&
      url.searchParams.get('path') === libraryPath('review', 'IMG_0300.jpg'));
    await expect(page.getByRole('heading', { name: 'IMG_0300.jpg', level: 1 })).toBeVisible();
    await expect(page.getByRole('img', { name: 'IMG_0300.jpg' })).toBeVisible();
  });

  await test.step('3. The Quality panel carries the seeded score, and the Histogram tab swaps the panel', async () => {
    await expect(page.getByRole('tabpanel', { name: 'Quality' })).toContainText(/Aesthetic\s*6\.0/);
    await page.getByRole('tab', { name: 'Histogram' }).click();
    await expect(page.getByRole('tab', { name: 'Histogram' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name: 'Quality' })).toHaveCount(0);
  });

  await test.step('4. Back returns to the gallery with the photo still listed', async () => {
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page).not.toHaveURL(/\/photo/);
    await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toBeVisible();
  });
});
