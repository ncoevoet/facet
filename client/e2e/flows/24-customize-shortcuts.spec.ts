import { test, expect } from '../fixtures';

// Customize shortcuts: rebinding Toggle favorite from F to G shows in the list, survives a reload,
// and Reset all brings F back.
test('a rebound shortcut persists and Reset all restores the default', async ({ page }) => {
  const open = async () => {
    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: 'Customize shortcuts' }).click();
    return page.getByRole('dialog', { name: /^Customize shortcuts/ });
  };
  await page.goto('/');

  await test.step('1. Toggle favorite starts on F', async () => {
    await expect(await open()).toContainText('Toggle favorite F');
  });

  await test.step('2. Rebind it to G', async () => {
    await page.getByRole('button', { name: /^Toggle favorite/ }).click();
    await page.keyboard.press('g');
    await expect(page.getByRole('button', { name: 'Toggle favorite G' })).toBeVisible();
    await page.getByRole('button', { name: 'OK' }).click();
  });

  await test.step('3. A reload keeps G', async () => {
    await page.reload();
    await expect(await open()).toContainText('Toggle favorite G');
  });

  await test.step('4. Reset all restores F', async () => {
    await page.getByRole('button', { name: 'Reset all' }).click();
    await expect(page.getByRole('button', { name: 'Toggle favorite F' })).toBeVisible();
    await page.getByRole('button', { name: 'OK' }).click();
    await page.reload();
    await expect(await open()).toContainText('Toggle favorite F');
  });
});
