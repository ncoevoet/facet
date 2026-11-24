import { test, expect, expectFailedLoad, libraryPath } from '../fixtures';

// From a gallery card to the photo page and back: the card opens its own photo, the page names it
// and shows its measurements, a tab switch shows another panel, and Back returns to the gallery.
test('a gallery card opens its photo page and Back returns to the gallery', async ({ page }) => {
  await test.step('1. The gallery lists the photo', async () => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toBeVisible();
  });

  await test.step('2. A double click opens that photo, not another', async () => {
    await page.getByRole('button', { name: 'IMG_0300.jpg', exact: true }).dblclick();
    await expect(page).toHaveURL(url => url.pathname === '/photo' &&
      url.searchParams.get('path') === libraryPath('review', 'IMG_0300.jpg'));
    await expect(page.getByRole('heading', { name: 'IMG_0300.jpg', level: 1 })).toBeVisible();
    await expect(page.getByRole('img', { name: 'IMG_0300.jpg' })).toBeVisible();
  });

  await test.step('3. The Quality panel carries the seeded score, and the Histogram tab swaps the panel', async () => {
    await expect(page.getByRole('tabpanel', { name: 'Quality' })).toContainText(/Aesthetic\s*6\.0/);
    await page.getByRole('tab', { name: 'Histogram' }).click();
    await expect(page.getByRole('tab', { name: 'Histogram' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name: 'Quality' })).toHaveCount(0);
  });

  await test.step('4. Back returns to the gallery with the photo still listed', async () => {
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page).not.toHaveURL(/\/photo/);
    await expect(page.getByRole('button', { name: 'IMG_0300.jpg', exact: true })).toBeVisible();
  });
});

test('both failed photo overlays can be retried independently', async ({ page }) => {
  const path = libraryPath('review', 'IMG_0300.jpg');
  const attempts = { faces: 0, objects: 0 };
  await page.addInitScript(() => localStorage.setItem('facet_face_box_mode', 'always'));
  // Route at the context to include requests forwarded by the active service worker.
  for (const kind of ['faces', 'objects'] as const) {
    const endpoint = new RegExp(`/api/photo/${kind}\\?`);
    expectFailedLoad(page, new RegExp(`^422 GET .*/api/photo/${kind}\\?`));
    await page.context().route(endpoint, async route => {
      if (new URL(route.request().url()).searchParams.get('path') !== path) {
        await route.fallback();
        return;
      }
      if (++attempts[kind] === 1) {
        await route.fulfill({ status: 422, json: { detail: 'Mock overlay read failure' } });
      } else {
        await route.fulfill({ json: { [kind]: [] } });
      }
    });
  }
  const canvas = page.getByRole('group', { name: 'Photo inspection' });
  const faces = canvas.getByRole('button', { name: 'Retry loading face boxes', exact: true });
  const objects = canvas.getByRole('button', { name: 'Retry loading object boxes', exact: true });

  await test.step('1. Both controls appear in separate rows when both reads fail', async () => {
    await page.goto(`/photo?path=${encodeURIComponent(path)}`);
    await expect(faces).toBeVisible();
    await expect(objects).toBeVisible();
    const faceBox = (await faces.boundingBox())!;
    const objectBox = (await objects.boundingBox())!;
    expect(faceBox.y + faceBox.height).toBeLessThanOrEqual(objectBox.y);
    expect(attempts).toEqual({ faces: 1, objects: 1 });
  });

  await test.step('2. A real click retries faces while the object error stays visible', async () => {
    await faces.click();
    await expect(faces).toHaveCount(0);
    await expect(objects).toBeVisible();
    expect(attempts).toEqual({ faces: 2, objects: 1 });
  });

  await test.step('3. A real click retries objects without reloading faces', async () => {
    await objects.click();
    await expect(objects).toHaveCount(0);
    expect(attempts).toEqual({ faces: 2, objects: 2 });
  });
});
