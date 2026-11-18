import { test, expect, unlockEdition, folderUrl } from '../fixtures';

// Download in the selection bar saves every selected original under its own file name, and Copy
// filenames puts the same names on the clipboard.
test('Download and Copy filenames act on the selected photos', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await unlockEdition(page);
  await page.goto(folderUrl('filter'));
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await page.getByRole('button', { name: 'IMG_0400.jpg', exact: true }).click();
  await page.getByRole('button', { name: 'IMG_0401.jpg', exact: true }).click();
  const downloads: string[] = [];
  page.on('download', (d) => downloads.push(d.suggestedFilename()));

  await test.step('1. Download saves both originals', async () => {
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Download' }).click();
    await expect.poll(() => [...downloads].sort()).toEqual(['IMG_0400.jpg', 'IMG_0401.jpg']);
  });

  await test.step('2. Copy filenames puts both names on the clipboard', async () => {
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Copy filenames' }).click();
    await expect.poll(async () => (await page.evaluate(() => navigator.clipboard.readText())).split(/\s+/).sort())
      .toEqual(expect.arrayContaining(['IMG_0400.jpg', 'IMG_0401.jpg']));
  });
});
