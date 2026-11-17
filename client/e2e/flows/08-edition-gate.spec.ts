import { test, expect, libraryPath } from '../fixtures';

// The shipped install is read-only until an edition password is given: an anonymous caller cannot
// delete a photo, a wrong password does not log in, and the photo is still there afterwards.
test('writes are refused without the edition password and nothing is deleted', async ({ page }) => {
  const target = libraryPath('review', 'IMG_0301.jpg');

  await test.step('1. An anonymous delete is refused', async () => {
    const res = await page.request.post('/api/photo/delete', { data: { paths: [target], dry_run: false } });
    expect([401, 403], `delete answered ${res.status()}`).toContain(res.status());
  });

  await test.step('2. A wrong edition password is refused', async () => {
    const res = await page.request.post('/api/auth/edition/login', { data: { password: 'not-the-password' } });
    expect(res.status()).toBe(401);
  });

  await test.step('3. An anonymous album create is refused', async () => {
    const res = await page.request.post('/api/albums', { data: { name: 'must not exist', description: '', is_smart: false } });
    expect([401, 403], `create answered ${res.status()}`).toContain(res.status());
  });

  await test.step('4. The photo is still in the gallery', async () => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'IMG_0301.jpg', exact: true })).toBeVisible();
  });
});
