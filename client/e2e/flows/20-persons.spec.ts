import { test, expect, seedTool, unlockEdition, cardNames } from '../fixtures';

// /persons lists the seeded person with its face count; renaming sticks across a reload and
// View photos opens the gallery filtered to that person's two photos.
test('a person can be renamed and opens its photos', async ({ page }) => {
  seedTool('reset', 'people');
  await unlockEdition(page);

  await test.step('1. /persons lists the seeded person', async () => {
    await page.goto('/persons');
    await expect(page.getByRole('button', { name: 'Ada E2E', exact: true })).toBeVisible();
  });

  await test.step('2. Rename it', async () => {
    await page.getByRole('button', { name: 'More' }).first().click();
    await page.getByRole('menuitem', { name: 'Rename' }).click();
    // The card edits the name in place, in an input of its own.
    await page.locator('app-person-card input').fill('Grace E2E');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Grace E2E', exact: true })).toBeVisible();
  });

  await test.step('3. The new name survives a reload', async () => {
    await page.reload();
    await expect(page.getByRole('button', { name: 'Grace E2E', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Ada E2E', exact: true })).toHaveCount(0);
  });

  await test.step('4. View photos opens the gallery on the two photos of that person', async () => {
    await page.getByRole('button', { name: 'View photos' }).first().click();
    await expect(page).toHaveURL(/person_id=\d+/);
    await expect.poll(async () => (await cardNames(page)).sort()).toEqual(['IMG_0800.jpg', 'IMG_0801.jpg']);
  });
});
