/** Resolve theme tokens for canvas, which cannot render CSS var() values itself. */
export function chartTheme(): { text: string; grid: string } {
  const style = getComputedStyle(document.documentElement);
  return {
    text: style.getPropertyValue('--mat-sys-on-surface-variant').trim() || '#465161',
    grid: style.getPropertyValue('--mat-sys-outline-variant').trim() || '#c4cbd5',
  };
}
