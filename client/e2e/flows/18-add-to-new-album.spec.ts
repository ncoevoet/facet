import { test, expect, editionToken, unlockEdition, folderUrl } from '../fixtures';

// From the selection bar: Add to Album > New Album names a new album and puts the selected photo
// in it; /albums then lists it and it opens to that photo alone.
test('a selected photo goes into a new album made from the selection bar', async ({ page }) => {
  const name = 'E2E picked from gallery';
  await unlockEdition(page);
  const headers = { Authorization: `Bearer ${await editionToken(page)}` };
  let albumId = 0;

  try {
    await test.step('1. Select a photo and create the album from Add to Album', async () => {
      await page.goto(folderUrl('filter'));
      await page.getByRole('button', { name: 'Select', exact: true }).click();
      await page.getByRole('button', { name: 'IMG_0404.jpg', exact: true }).click();
      await page.getByRole('button', { name: 'Actions', exact: true }).click();
      await page.getByRole('menuitem', { name: 'Add to Album' }).click();
      await page.getByRole('menuitem', { name: 'New Album' }).click();
      await page.getByRole('textbox', { name: 'Album Name' }).fill(name);
      await page.getByRole('dialog', { name: 'New Album' }).getByRole('button', { name: 'New Album' }).click();
      await expect(page.getByText('Photos added to album')).toBeVisible();
    });

    await test.step('2. /albums lists the album', async () => {
      await page.goto('/albums');
      await expect(page.getByText(name, { exact: true })).toBeVisible();
      const list = await (await page.request.get('/api/albums', { headers })).json();
      albumId = (list.albums ?? list).find((a: { name: string }) => a.name === name).id;
    });

    await test.step('3. It opens to the selected photo and nothing else', async () => {
      await page.goto(`/album/${albumId}`);
      await expect(page.getByRole('button', { name: 'IMG_0404.jpg', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'IMG_0403.jpg', exact: true })).toHaveCount(0);
    });
  } finally {
    if (albumId) {
      await test.step('4. Delete the album; the photo stays in the library', async () => {
        expect((await page.request.delete(`/api/albums/${albumId}`, { headers })).ok()).toBeTruthy();
        await page.goto(folderUrl('filter'));
        await expect(page.getByRole('button', { name: 'IMG_0404.jpg', exact: true })).toBeVisible();
      });
    }
  }
});
