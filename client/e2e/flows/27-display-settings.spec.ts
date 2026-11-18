import { test, expect } from '../fixtures';

// The gallery Display menu keeps its switches in the browser: Fast scrolling, on by default, is off
// after being switched and a reload, and on again once switched back.
test('a Display switch persists across a reload', async ({ page }) => {
  const fastScrolling = async () => {
    await page.getByRole('button', { name: 'Display' }).click();
    return page.getByRole('checkbox', { name: 'Fast scrolling' });
  };
  await page.goto('/');

  await test.step('1. Fast scrolling starts on', async () => {
    await expect(await fastScrolling()).toBeChecked();
  });

  await test.step('2. Switch it off: it stays off after a reload', async () => {
    await page.getByRole('checkbox', { name: 'Fast scrolling' }).click();
    await page.reload();
    await expect(await fastScrolling()).not.toBeChecked();
  });

  await test.step('3. Switch it back on: it stays on after a reload', async () => {
    await page.getByRole('checkbox', { name: 'Fast scrolling' }).click();
    await page.reload();
    await expect(await fastScrolling()).toBeChecked();
  });
});
