import { test, expect, expectFailedLoad, folderUrl, libraryPath } from '../fixtures';

const path = libraryPath('review', 'IMG_0300.jpg');
const photoUrl = `/photo?path=${encodeURIComponent(path)}`;
const setting = 'Show image source information';

for (const [name, viewport] of [
  ['desktop', { width: 1440, height: 900 }],
  ['phone', { width: 390, height: 844 }],
  ['small phone', { width: 320, height: 740 }],
] as const) {
  test(`the photo source readout can be hidden and restored on ${name}`, async ({ page }, info) => {
    await page.setViewportSize(viewport);
    await page.goto(folderUrl('review'));
    await page.getByRole('button', { name: 'IMG_0300.jpg', exact: true }).dblclick();
    await expect(page).toHaveURL(url => url.pathname === '/photo');
    const readout = page.locator('[data-image-readout]');
    const canvas = page.getByRole('group', { name: 'Photo inspection', exact: true });
    const openSetting = async () => {
      await page.getByRole('button', { name: 'User menu', exact: true }).click();
      await page.getByRole('menuitem', { name: 'Display', exact: true }).click();
      return page.getByRole('menuitemcheckbox', { name: setting, exact: true });
    };

    await test.step('1. Source information is shown by default', async () => {
      await expect(readout.getByRole('status')).toContainText('Source image');
    });

    await test.step('2. Hide the row: zoom controls float inside the image', async () => {
      const toggle = await openSetting();
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      await toggle.click();
      await expect(readout.getByRole('status')).toHaveCount(0);
      await expect(readout.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible();
      const image = (await canvas.boundingBox())!;
      const controls = (await readout.boundingBox())!;
      expect(controls.y).toBeGreaterThanOrEqual(image.y);
      expect(controls.y + controls.height).toBeLessThanOrEqual(image.y + image.height);
      for (const button of await readout.getByRole('button').all()) {
        const bounds = (await button.boundingBox())!;
        expect(bounds.x).toBeGreaterThanOrEqual(image.x);
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(image.x + image.width);
      }
      const position = (await page.locator('[data-collection-position]').boundingBox())!;
      expect(position.x + position.width).toBeLessThanOrEqual(controls.x);
      await page.screenshot({ path: info.outputPath('compact-readout.png') });
      await readout.getByRole('button', { name: 'Zoom in', exact: true }).click();
      await expect(readout.getByRole('button', { name: /^Fit image/ })).toHaveAccessibleName(/×/);
      await readout.getByRole('button', { name: /^Fit image/ }).click();
      await expect(readout.getByRole('button', { name: 'Fit image', exact: true })).toBeVisible();
    });

    await test.step('3. Reload keeps it hidden and the setting can restore it', async () => {
      await page.reload();
      await expect(readout.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible();
      await expect(readout.getByRole('status')).toHaveCount(0);
      const toggle = await openSetting();
      await expect(toggle).toHaveAttribute('aria-checked', 'false');
      await toggle.click();
      await expect(readout.getByRole('status')).toContainText('Source image');
    });
  });
}

test('a hidden source readout still reports a failed image and retries it', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('facet_photo_source_readout', 'false'));
  expectFailedLoad(page, /^404 GET .*\/image\?/);
  let attempts = 0;
  let started!: () => void;
  let release!: () => void;
  const retryStarted = new Promise<void>(resolve => { started = resolve; });
  const retryReleased = new Promise<void>(resolve => { release = resolve; });
  await page.context().route(/\/image\?/, async route => {
    if (new URL(route.request().url()).searchParams.get('path') !== path) {
      await route.fallback();
      return;
    }
    if (++attempts === 1) await route.fulfill({ status: 404, body: 'Source unavailable' });
    else {
      started();
      await retryReleased;
      await route.continue();
    }
  });
  await page.goto(photoUrl);
  const readout = page.locator('[data-image-readout]');
  await expect(readout).toContainText('Source image unavailable');
  await readout.getByRole('button', { name: 'Retry', exact: true }).click();
  await retryStarted;
  try { await expect(readout).toContainText('Requested rendition loading'); }
  finally { release(); }
  await expect(readout.getByRole('status')).toHaveCount(0);
  await expect(readout.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0);
  await expect(readout.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible();
  expect(attempts).toBe(2);
});
