import { MOBILE_BAR_ROW, MOBILE_DOCKED_BAR_ROW } from './mobile-bar';

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
});
