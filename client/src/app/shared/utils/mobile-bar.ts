/**
 * One row of the fixed bottom bar a page shows below `lg`: every bar is 56 px tall
 * with the same inset and gap, whatever its page. Every icon button in it is a 44 px
 * square with its glyph centred: Material places an icon button's glyph with its
 * density padding (6 px here), so a button only stretched to 44 px kept its glyph
 * 1 to 4 px above centre, and one left at 36 px missed the touch target.
 */
export const MOBILE_BAR_ROW = 'flex min-h-14 items-center gap-1 px-2 py-1'
  + ' [&_.mat-mdc-icon-button]:!inline-flex [&_.mat-mdc-icon-button]:!items-center [&_.mat-mdc-icon-button]:!justify-center'
  + ' [&_.mat-mdc-icon-button]:!p-0 [&_.mat-mdc-icon-button]:!size-11';

/**
 * Lifts a snackbar above the bottom bars, and a phone's home-indicator notch, below `lg`. Applied to
 * every snackbar through `MAT_SNACK_BAR_DEFAULT_OPTIONS`, so no toast is opened under a bar.
 */
export const SNACKBAR_LIFT_CLASS = 'max-lg:!mb-[calc(4rem+env(safe-area-inset-bottom))]';

/** The same row, icon buttons included, for a page toolbar that docks at the bottom only below `lg`. */
export const MOBILE_DOCKED_BAR_ROW = 'max-lg:min-h-14 max-lg:items-center max-lg:gap-1 max-lg:px-2 max-lg:py-1'
  + ' max-lg:[&_.mat-mdc-icon-button]:!inline-flex max-lg:[&_.mat-mdc-icon-button]:!items-center max-lg:[&_.mat-mdc-icon-button]:!justify-center'
  + ' max-lg:[&_.mat-mdc-icon-button]:!p-0 max-lg:[&_.mat-mdc-icon-button]:!size-11';

/**
 * A text button in a page's mobile bar: 44 px touch target, and below `md` the label
 * span is hidden and the button shrinks to its icon alone. Pair it with a
 * `<span class="max-md:hidden">` around the label; display utilities on Material hosts need `!`.
 */
export const MOBILE_BAR_BUTTON = '!h-11 !min-w-11 shrink-0 max-md:!px-0 max-md:[&>mat-icon]:!m-0';

/**
 * A text button whose label shows only from `xl` (`<span class="hidden xl:inline">`): below `xl` it is
 * an icon alone, so it drops Material's leading-icon margins (-4 px before, 8 px after), which would
 * otherwise sit its glyph 6 px left of the button's centre.
 */
export const XL_LABEL_BUTTON = 'max-xl:[&>mat-icon]:!m-0';
