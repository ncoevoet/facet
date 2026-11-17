import { TimestampPipe } from './timestamp.pipe';

describe('TimestampPipe', () => {
  const pipe = new TimestampPipe();
  const instant = '2026-10-03T21:07:00Z';

  it.each([
    ['en', '3 Oct 2026 21:07'],
    ['fr', '3 oct. 2026 21:07'],
    ['de', '3. Okt. 2026 21:07'],
    ['zh', '2026年10月3日 21:07'],
  ])('writes the UTC day the way %s does, day first in English', (language, expected) => {
    expect(pipe.transform(instant, language, 'datetime', 'UTC')).toBe(expected);
  });

  it('reads epoch milliseconds and Date values alike', () => {
    const ms = Date.parse(instant);
    expect(pipe.transform(ms, 'en', 'datetime', 'UTC')).toBe('3 Oct 2026 21:07');
    expect(pipe.transform(new Date(ms), 'en', 'datetime', 'UTC')).toBe('3 Oct 2026 21:07');
  });

  it('renders in the browser timezone by default', () => {
    const local = new Date(2026, 9, 3, 8, 5);
    expect(pipe.transform(local, 'en')).toBe('3 Oct 2026 08:05');
  });

  it('drops the time in date mode', () => {
    expect(pipe.transform(instant, 'en', 'date', 'UTC')).toBe('3 Oct 2026');
  });

  it.each([null, undefined, '', 'not a date'])('renders %s as empty', value => {
    expect(pipe.transform(value, 'en')).toBe('');
  });
});
