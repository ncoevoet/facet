import { test, expect } from '../fixtures';

// Every top-level page loads on a seeded library without a page error, a console error or a 5xx
// answer (the `gate` fixture fails the flow on any of them) and stays on its own URL: a route that
// bounces to /login or to the 404 catch-all is a regression the unit tests cannot see.
const ROUTES = [
  '/albums',
  '/capsules',
  '/compare',
  '/culling',
  '/folders',
  '/junk',
  '/map',
  '/persons',
  '/scenes',
  '/stats',
  '/timeline',
];

for (const route of ROUTES) {
  test(`${route} loads without an error`, async ({ page }) => {
    await test.step(`1. Open ${route}`, async () => {
      await page.goto(route);
      await expect(page).toHaveURL(new RegExp(`${route}(\\?.*)?$`));
    });

    await test.step('2. The page renders something and the network settles', async () => {
      await expect(page.locator('app-root')).not.toBeEmpty();
      await page.waitForLoadState('networkidle');
    });
  });
}
