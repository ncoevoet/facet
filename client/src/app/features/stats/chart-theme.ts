/** Resolve theme tokens for canvas, which cannot render CSS var() values itself. */
export function chartTheme(): { text: string; grid: string } {
  const style = getComputedStyle(document.documentElement);
  return {
    text: style.getPropertyValue('--mat-sys-on-surface-variant').trim() || '#465161',
    grid: style.getPropertyValue('--mat-sys-outline-variant').trim() || '#c4cbd5',
  };
}

/** Series colours chosen to remain distinguishable from light and dark cards. */
export function chartSeriesColors(dark: boolean): readonly string[] {
  return dark
    ? ['#56d788', '#7aabff', '#d38be9', '#ffc164', '#ff8c8c', '#62d8e5', '#ff9dd6', '#b8d85e']
    : ['#176a3a', '#2459a8', '#963c96', '#8a4d00', '#b12f33', '#006d75', '#aa2770', '#526b00'];
}

/** Keep a supplied hex accent only when it contrasts with the chart surface. */
export function chartSeriesColor(color: string, dark: boolean, fallbackIndex = 0): string {
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (match) {
    const channels = match[1].match(/../g)!.map(part => parseInt(part, 16) / 255)
      .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    // Allow room for translucent fills and for surfaces near, not exactly at,
    // the extremes.  #303030 is lighter than the default dark card.
    const contrast = dark ? (luminance + 0.05) / (0.0296 + 0.05) : 1.05 / (luminance + 0.05);
    if (contrast >= 4.5) return color;
  }
  const palette = chartSeriesColors(dark);
  return palette[((fallbackIndex % palette.length) + palette.length) % palette.length];
}
