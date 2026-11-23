import { test, expect } from '../fixtures';

test('clearing the final capsule date filter reloads the unfiltered grid', async ({ page }) => {
  const requests: URL[] = [];
  // Include requests forwarded by the service worker, which stays enabled.
  page.context().on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === '/api/capsules') requests.push(url);
  });
  await page.goto('/capsules');
  const golden = page.getByRole('button', { name: 'Golden Collection', exact: true });
  await expect(golden).toBeVisible();
  const from = page.locator('input[type="date"]:visible').first();
  await from.fill('2099-01-01');
  await from.press('Tab');
  await expect(page.getByText('No capsules available yet. Keep adding photos!', { exact: true })).toBeVisible();
  await from.fill('');
  await from.press('Tab');
  await expect(golden).toBeVisible();
  expect(requests.at(-1)?.searchParams.get('page')).toBe('1');
  expect(requests.at(-1)?.searchParams.has('date_from')).toBe(false);
});
