import { test, expect, unlockEdition } from '../fixtures';

// Connect an assistant: a named token is created, its connection prompt is shown once, it is listed under
// Manage tokens, and revoking it empties the list again.
test('an assistant token can be created and revoked', async ({ page }) => {
  await unlockEdition(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('menuitem', { name: 'Connect an assistant' }).click();
  const dialog = page.getByRole('dialog', { name: 'Connect an assistant' });

  await test.step('1. Create is disabled until the token has a name', async () => {
    await expect(dialog.getByRole('button', { name: 'Create token' })).toBeDisabled();
    await dialog.getByRole('textbox', { name: 'Name' }).fill('e2e assistant');
    await expect(dialog.getByRole('button', { name: 'Create token' })).toBeEnabled();
  });

  await test.step('2. Creating it shows the prompt once, then lists the token under Manage tokens', async () => {
    await dialog.getByRole('button', { name: 'Create token' }).click();
    await expect(dialog.getByText('Paste this into your assistant')).toBeVisible();
    const prompt = dialog.locator('textarea');
    await expect(prompt).toHaveValue(/Authorization: Bearer fct_/);
    await expect(prompt).toHaveValue(/Access granted: Read and pilot only/);
    await dialog.getByRole('button', { name: 'Done' }).click();
    await expect(dialog.getByText('Paste this into your assistant')).toHaveCount(0);
    await expect(dialog.getByText('Manage tokens (1)')).toBeVisible();
    await dialog.getByText('Manage tokens (1)').click();
    await expect(dialog.getByRole('button', { name: /Revoke/ })).toHaveCount(1);
  });

  await test.step('3. Revoking it empties the list', async () => {
    await dialog.getByRole('button', { name: /Revoke/ }).click();
    await dialog.getByRole('button', { name: 'Yes, revoke' }).click();
    await expect(dialog.getByText('Manage tokens (0)')).toBeVisible();
  });
});
