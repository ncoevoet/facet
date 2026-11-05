import { chartSeriesColor, chartSeriesColors } from './chart-theme';

function luminance(hex: string): number {
  const channels = hex.slice(1).match(/../g)!.map(part => parseInt(part, 16) / 255)
    .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

describe('statistics chart palette', () => {
  it('keeps opaque and 80% filled series legible on a white card', () => {
    for (const color of chartSeriesColors(false)) {
      const blended = '#' + color.slice(1).match(/../g)!.map(part => Math.round(parseInt(part, 16) * .8 + 255 * .2).toString(16).padStart(2, '0')).join('');
      expect(1.05 / (luminance(blended) + .05)).toBeGreaterThanOrEqual(3);
    }
  });

  it('keeps 80% filled series legible on a dark card', () => {
    const background = luminance('#303030');
    for (const color of chartSeriesColors(true)) {
      const blended = '#' + color.slice(1).match(/../g)!.map(part => Math.round(parseInt(part, 16) * .8 + 48 * .2).toString(16).padStart(2, '0')).join('');
      expect((luminance(blended) + .05) / (background + .05)).toBeGreaterThanOrEqual(3);
    }
  });

  it('replaces low contrast custom accents while keeping contrasting ones', () => {
    expect(chartSeriesColor('#f4d000', false)).toBe(chartSeriesColors(false)[0]);
    expect(chartSeriesColor('#2459a8', false)).toBe('#2459a8');
    expect(chartSeriesColor('#262626', true)).toBe(chartSeriesColors(true)[0]);
  });
});
