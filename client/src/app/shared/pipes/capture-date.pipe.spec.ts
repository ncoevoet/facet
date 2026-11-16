import { CaptureDatePipe } from './capture-date.pipe';

describe('CaptureDatePipe', () => {
  const pipe = new CaptureDatePipe();

  it.each([
    ['2026:10:31 23:05:42', '31 Oct 2026 23:05'],
    ['2026-10-31T23:05:42Z', '31 Oct 2026 23:05'],
    ['2026-10-31T23:05:42+05:30', '31 Oct 2026 23:05'],
    ['2024:02:29', '29 Feb 2024'],
  ])('formats the recorded calendar fields of %s day first in English, without timezone conversion', (source, expected) => {
    expect(pipe.transform(source, 'en')).toBe(expected);
  });

  it('renders the zh date the way Chinese writes it', () => {
    expect(pipe.transform('2026:10:31 23:05:42', 'zh')).toBe('2026年10月31日 23:05');
    expect(pipe.transform('2024:02:29', 'zh')).toBe('2024年2月29日');
  });

  it('formats with the language it is given, without shifting the recorded fields', () => {
    expect(pipe.transform('2026:10:31 23:05:42', 'de')).toBe('31. Okt. 2026 23:05');
    expect(pipe.transform('2026:10:31 23:05:42', 'fr')).toBe('31 oct. 2026 23:05');
  });

  it.each(['unknown', '2026:02:29', '2026:13:01', '2026:10:31 24:05:00'])('preserves unsupported or invalid capture values: %s', value => {
    expect(pipe.transform(value, 'en')).toBe(value);
  });

  it('keeps missing metadata empty', () => {
    expect(pipe.transform(null, 'en')).toBe('');
    expect(pipe.transform(undefined, 'en')).toBe('');
  });
});
