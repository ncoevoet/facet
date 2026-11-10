/**
 * One row of the fixed bottom bar a page shows below `lg`: every bar is 56 px tall
 * with the same inset and gap, whatever its page.
 */
export const MOBILE_BAR_ROW = 'flex min-h-14 items-center gap-1 px-2 py-1';

/**
 * Lifts a snackbar above the bottom bars, and a phone's home-indicator notch, below `lg`. Applied to
 * every snackbar through `MAT_SNACK_BAR_DEFAULT_OPTIONS`, so no toast is opened under a bar.
 */
export const SNACKBAR_LIFT_CLASS = 'max-lg:!mb-[calc(4rem+env(safe-area-inset-bottom))]';

/** The same row for a page toolbar that docks at the bottom only below `lg`. */
export const MOBILE_DOCKED_BAR_ROW = 'max-lg:min-h-14 max-lg:items-center max-lg:gap-1 max-lg:px-2 max-lg:py-1';

/**
 * A text button in a page's mobile bar: 44 px touch target, and below `md` the label
 * span is hidden and the button shrinks to its icon alone. Pair it with a
 * `<span class="max-md:hidden">` around the label; display utilities on Material hosts need `!`.
 */
export const MOBILE_BAR_BUTTON = '!h-11 !min-w-11 shrink-0 max-md:!px-0 max-md:[&>mat-icon]:!m-0';
