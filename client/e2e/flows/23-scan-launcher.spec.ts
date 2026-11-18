import { test, expect, unlockEdition, WORK } from '../fixtures';

// The scan launcher (edition only, behind features.show_scan_button) lists the configured library
// folder and preselects it, since it is the only one. The flow never starts a scan: a real one would run the scoring models.
test('the scan launcher offers the library folder without starting a scan', async ({ page }) => {
  await unlockEdition(page);
  await page.goto('/');
  const dialog = page.getByRole('dialog');

  await test.step('1. The header scan button opens the launcher', async () => {
    await page.getByRole('button', { name: /^Scan/ }).click();
    await expect(dialog).toBeVisible();
  });

  await test.step('2. The configured library folder is offered, already chosen, and Start is ready', async () => {
    await expect(dialog.getByText(`${WORK}/library`)).toBeVisible();
    await expect(dialog.getByRole('radio')).toBeChecked();
    await expect(dialog.getByRole('button', { name: /^Start/ })).toBeEnabled();
  });

  await test.step('3. Close dismisses it without starting anything', async () => {
    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toHaveCount(0);
  });
});
