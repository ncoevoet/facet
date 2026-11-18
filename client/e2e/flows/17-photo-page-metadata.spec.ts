import { test, expect, seedTool, unlockEdition, libraryPath } from '../fixtures';

// Metadata edits on the photo page: a caption, a manual tag and a capture-date shift are saved
// and still shown after a reload, which reads them back from the server.
test('a caption, a tag and a corrected capture date survive a reload', async ({ page }) => {
  seedTool('reset', 'edit');
  await unlockEdition(page);
  await page.goto(`/photo?path=${encodeURIComponent(libraryPath('edit', 'IMG_0600.jpg'))}`);
  const details = page.getByRole('complementary', { name: 'Photo details' });

  await test.step('1. The photo starts on 16 Apr 2026 10:00 with no caption', async () => {
    await expect(details).toContainText('16 Apr 2026 10:00');
    await expect(details.getByRole('button', { name: 'Add caption' })).toBeVisible();
  });

  await test.step('2. Save a caption', async () => {
    await details.getByRole('button', { name: 'Add caption' }).click();
    await page.getByRole('textbox', { name: 'Caption' }).fill('a grey wall in the rain');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(details).toContainText('a grey wall in the rain');
  });

  await test.step('3. Add a tag', async () => {
    await details.getByRole('button', { name: 'Add tag' }).click();
    await page.getByRole('textbox', { name: 'Add tag' }).fill('e2e-wall');
    await page.keyboard.press('Enter');
    await expect(details).toContainText('e2e-wall');
  });

  await test.step('4. Shift the capture date one hour later', async () => {
    await details.getByRole('button', { name: 'Correct capture date' }).click();
    const dialog = page.getByRole('dialog', { name: 'Correct capture date' });
    await expect(dialog.getByRole('cell', { name: '2026:04:16 11:00:00' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Apply correction (1)' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(details).toContainText('16 Apr 2026 11:00');
  });

  await test.step('5. A reload shows all three', async () => {
    await page.reload();
    await expect(details).toContainText('a grey wall in the rain');
    await expect(details).toContainText('e2e-wall');
    await expect(details).toContainText('16 Apr 2026 11:00');
  });
});
