import { CaptureDatePipe } from './capture-date.pipe';

describe('CaptureDatePipe', () => {
  const pipe = new CaptureDatePipe();

  it.each([
    ['2026:10:31 23:05:42', '31/10/2026 23:05'],
    ['2026-10-31T23:05:42Z', '31/10/2026 23:05'],
    ['2026-10-31T23:05:42+05:30', '31/10/2026 23:05'],
    ['2024:02:29', '29/02/2024'],
  ])('formats the recorded calendar fields of %s without timezone conversion', (source, expected) => {
    expect(pipe.transform(source)).toBe(expected);
  });

  it.each(['unknown', '2026:02:29', '2026:13:01', '2026:10:31 24:05:00'])('preserves unsupported or invalid capture values: %s', value => {
    expect(pipe.transform(value)).toBe(value);
  });

  it('keeps missing metadata empty', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
