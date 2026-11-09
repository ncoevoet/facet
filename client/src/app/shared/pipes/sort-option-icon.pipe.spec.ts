import { MarkTonePipe } from './mark-tone.pipe';
import { SortOptionIconPipe, STATS_OPTION_ALIASES } from './sort-option-icon.pipe';

describe('SortOptionIconPipe', () => {
  const pipe = new SortOptionIconPipe();

  it('returns a model label for model columns', () => {
    expect(pipe.transform('aesthetic_iaa')).toEqual({ text: 'IAA', classes: '!font-sans !text-[11px] !font-semibold !leading-6' });
  });

  it('returns an icon ligature for mapped columns', () => {
    expect(pipe.transform('date_taken')).toEqual({ text: 'event', classes: '' });
  });

  it('draws the aesthetic sort with the quality mark in its colour, never the AI sparkle', () => {
    expect(pipe.transform('aesthetic')).toEqual({ text: '✦', classes: new MarkTonePipe().transform('quality') });
  });

  it('falls back to sort for unknown columns', () => {
    expect(pipe.transform('unknown')).toEqual({ text: 'sort', classes: '' });
  });

  it('does not resolve Object.prototype members', () => {
    expect(pipe.transform('constructor')).toEqual({ text: 'sort', classes: '' });
    expect(pipe.transform('toString')).toEqual({ text: 'sort', classes: '' });
  });

  it('resolves the stats metric aliases to the gallery sort icon, tone and badge included', () => {
    expect(pipe.transform('avg_score')).toEqual(pipe.transform('aggregate'));
    expect(pipe.transform('avg_aesthetic')).toEqual(pipe.transform('aesthetic'));
    expect(pipe.transform('avg_aesthetic').text).toBe('✦');
    expect(pipe.transform('avg_sharpness')).toEqual(pipe.transform('tech_sharpness'));
    expect(pipe.transform('avg_contrast')).toEqual(pipe.transform('contrast_score'));
    expect(pipe.transform('avg_f_stop')).toEqual(pipe.transform('f_stop'));
    expect(pipe.transform('avg_focal_length')).toEqual(pipe.transform('focal_length'));
    expect(pipe.transform('avg_iso')).toEqual(pipe.transform('iso'));
  });

  it('draws the stats-only keys with their own icons instead of the sort fallback', () => {
    for (const key of ['count', 'iso', 'usage_timeline', 'camera_model', 'lens_model', 'date_month', 'date_year', 'category', 'line', 'area', 'bar', 'horizontalBar']) {
      expect(pipe.transform(key).text, key).not.toBe('sort');
    }
    expect(pipe.transform('camera_model')).toEqual({ text: 'photo_camera', classes: '' });
  });

  it('keeps every alias target resolvable', () => {
    for (const target of Object.values(STATS_OPTION_ALIASES)) {
      expect(pipe.transform(target).text, target).not.toBe('sort');
    }
  });
});
