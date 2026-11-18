import { test, expect, folderUrl, expectFailedLoad } from '../fixtures';
import { EDITION_PASSWORD } from '../env';

// The Edition dialog from the user menu: a wrong password is refused in place, the right one
// unlocks editing (the menu gains "Jobs & diagnostics", the selection bar gains write actions).
test('the edition dialog refuses a wrong password and unlocks with the right one', async ({ page }) => {
  expectFailedLoad(page, /^401 POST .*\/api\/auth\/edition\/login$/);
  await page.goto(folderUrl('filter'));
  const password = page.getByRole('textbox', { name: 'Edition password' });

  await test.step('1. Anonymous: the user menu offers Edition but no diagnostics', async () => {
    await page.getByRole('button', { name: 'User menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'Jobs & diagnostics' })).toHaveCount(0);
    await page.getByRole('menuitem', { name: /Edition/ }).click();
    await expect(page.getByRole('dialog', { name: 'Unlock Edition Mode' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Unlock' })).toBeDisabled();
  });

  await test.step('2. A wrong password shows an error and the dialog stays open', async () => {
    await password.fill('not-the-password');
    await page.getByRole('button', { name: 'Unlock' }).click();
    await expect(page.getByText('Invalid password')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Unlock Edition Mode' })).toBeVisible();
  });

  await test.step('3. The right password closes the dialog', async () => {
    await password.fill(EDITION_PASSWORD);
    await page.getByRole('button', { name: 'Unlock' }).click();
    await expect(page.getByRole('dialog', { name: 'Unlock Edition Mode' })).toHaveCount(0);
  });

  await test.step('4. Unlocked: the menu gains Jobs & diagnostics', async () => {
    await page.getByRole('button', { name: 'User menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'Jobs & diagnostics' })).toBeVisible();
    await page.keyboard.press('Escape');
  });

  await test.step('5. After a reload still unlocked: the selection menu offers writes it hid before', async () => {
    await page.goto(folderUrl('filter'));
    await expect(page.getByRole('gridcell').first()).toBeVisible();
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await page.getByRole('gridcell').first().getByRole('button').first().click();
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'Add to Album' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: 'Delete…' })).toBeVisible();
  });
});
