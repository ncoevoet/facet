import { test, expect, seedTool, unlockEdition, folderUrl, cardNames } from '../fixtures';

// Delete… in the selection bar: Cancel leaves the photo, confirming sends it to the (test) trash
// and the gallery stops listing it while its neighbour stays.
test('Delete from the selection bar removes only the confirmed photo', async ({ page }) => {
  seedTool('reset', 'trash');
  await unlockEdition(page);

  await test.step('1. Select IMG_0700 and open Delete…: the dialog names one photo', async () => {
    await page.goto(folderUrl('trash'));
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await page.getByRole('button', { name: 'IMG_0700.jpg', exact: true }).click();
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Delete…' }).click();
    await expect(page.getByRole('dialog', { name: 'Delete photos?' })).toContainText('1 photos');
  });

  await test.step('2. Cancel deletes nothing', async () => {
    await page.getByRole('dialog', { name: 'Delete photos?' }).getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('dialog', { name: 'Delete photos?' })).toHaveCount(0);
    await expect.poll(async () => (await cardNames(page)).sort()).toEqual(['IMG_0700.jpg', 'IMG_0701.jpg']);
  });

  await test.step('3. Confirming deletes IMG_0700 and keeps IMG_0701', async () => {
    await page.getByRole('button', { name: 'Actions', exact: true }).click();
    await page.getByRole('menuitem', { name: 'Delete…' }).click();
    const answer = page.waitForResponse((r) => r.url().includes('/api/photo/delete') && r.request().method() === 'POST');
    await page.getByRole('dialog', { name: 'Delete photos?' }).getByRole('button', { name: 'Delete…' }).click();
    expect((await answer).ok()).toBeTruthy();
  });

  await test.step('4. After a reload only IMG_0701 is listed', async () => {
    await page.goto(folderUrl('trash'));
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0701.jpg']);
  });
});
