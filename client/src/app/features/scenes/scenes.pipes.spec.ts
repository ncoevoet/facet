import { SceneDatePipe, MomentLabelPipe, MomentUncertainPipe } from './scenes.pipes';

describe('SceneDatePipe', () => {
  const pipe = new SceneDatePipe();

  it('reformats an EXIF timestamp to DD/MM/YYYY HH:MM', () => {
    expect(pipe.transform('2024:06:15 10:05:00')).toBe('15/06/2024 10:05');
  });

  it('handles ISO-style separators', () => {
    expect(pipe.transform('2024-06-15T10:05:00')).toBe('15/06/2024 10:05');
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('passes through an unparseable value', () => {
    expect(pipe.transform('not-a-date')).toBe('not-a-date');
  });
});

describe('MomentLabelPipe', () => {
  const pipe = new MomentLabelPipe();

  it('prettifies a moment key', () => {
    expect(pipe.transform('first_dance')).toBe('First Dance');
  });

  it('hides the "other" gate outcome', () => {
    expect(pipe.transform('other')).toBe('');
  });

  it('returns empty for null/empty', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform('')).toBe('');
  });
});

describe('MomentUncertainPipe', () => {
  const pipe = new MomentUncertainPipe();

  it('is uncertain when confidence is below the threshold', () => {
    expect(pipe.transform(0.4, 0.6)).toBe(true);
  });

  it('is confident at or above the threshold', () => {
    expect(pipe.transform(0.8, 0.6)).toBe(false);
  });

  it('never dims when threshold is 0 or missing', () => {
    expect(pipe.transform(0.1, 0)).toBe(false);
    expect(pipe.transform(0.1, null)).toBe(false);
  });

  it('never dims when confidence is null', () => {
    expect(pipe.transform(null, 0.6)).toBe(false);
  });
});
