import { test, expect, seedTool, unlockEdition, cardNames, folderUrl } from '../fixtures';

// /culling proposes a keeper per burst. Flipping a frame to kept and confirming the group rejects
// only the frame left out; the gallery then hides that one and still lists the two kept.
test('confirming a culling group rejects only the frame left out', async ({ page }) => {
  seedTool('reset', 'cull');
  await unlockEdition(page);

  await test.step('1. /culling proposes IMG_0500 only: the other two frames start rejected', async () => {
    await page.goto('/culling');
    await expect(page.getByRole('button', { name: 'IMG_0500.jpg, Kept' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'IMG_0501.jpg, Rejected' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'IMG_0502.jpg, Rejected' })).toBeVisible();
  });

  await test.step('2. Clicking IMG_0501 flips it to kept', async () => {
    await page.getByRole('button', { name: 'IMG_0501.jpg, Rejected' }).click();
    await expect(page.getByRole('button', { name: 'IMG_0501.jpg, Kept' })).toBeVisible();
  });

  await test.step('3. Confirm sends the decision once the undo cooldown ends', async () => {
    const group = page.locator('[data-culling-group-key]').filter({ has: page.getByRole('button', { name: /^IMG_0502\.jpg/ }) });
    const answer = page.waitForResponse((r) => r.url().includes('/culling-groups/confirm'), { timeout: 20_000 });
    await group.getByRole('button', { name: 'Confirm', exact: true }).click();
    const res = await answer;
    expect(res.status()).toBe(200);
    expect(await res.json()).toMatchObject({ status: 'ok', kept: 2, rejected: 1 });
  });

  await test.step('4. The gallery lists the two kept frames and no longer the rejected one', async () => {
    await page.goto(folderUrl('cull'));
    await expect.poll(() => cardNames(page)).toEqual(['IMG_0500.jpg', 'IMG_0501.jpg']);
  });
});
