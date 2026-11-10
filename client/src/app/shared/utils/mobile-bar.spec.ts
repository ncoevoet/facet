import { MOBILE_BAR_ROW, MOBILE_DOCKED_BAR_ROW, TOUCH_ICON_BUTTON, TOUCH_TEXT_BUTTON } from './mobile-bar';

describe('mobile bar rows', () => {
  const iconButton = ['!inline-flex', '!items-center', '!justify-center', '!p-0', '!size-11'];

  it('makes every icon button in a bottom bar a 44 px square with its glyph centred', () => {
    const utilities = MOBILE_BAR_ROW.split(' ');
    for (const rule of iconButton) expect(utilities).toContain(`[&_.mat-mdc-icon-button]:${rule}`);
  });

  it('gives a toolbar that docks at the bottom below lg the same icon buttons there, and only there', () => {
    const utilities = MOBILE_DOCKED_BAR_ROW.split(' ');
    for (const rule of iconButton) expect(utilities).toContain(`max-lg:[&_.mat-mdc-icon-button]:${rule}`);
    expect(utilities.filter(utility => utility.includes('mat-mdc-icon-button') && !utility.startsWith('max-lg:'))).toEqual([]);
  });

  it('sizes a toolbar icon button 44 px square and a text button 44 px tall, below sm and on a coarse pointer', () => {
    expect(TOUCH_ICON_BUTTON.split(' ').sort()).toEqual(
      ['max-sm:!h-11', 'max-sm:!w-11', 'pointer-coarse:!h-11', 'pointer-coarse:!w-11']);
    expect(TOUCH_TEXT_BUTTON.split(' ').sort()).toEqual(['max-sm:!min-h-11', 'pointer-coarse:!min-h-11']);
  });
});
