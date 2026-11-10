import { describe, expect, it } from 'vitest';
import { SectionOpenPipe } from './section-open.pipe';

describe('SectionOpenPipe', () => {
  const pipe = new SectionOpenPipe();
  it('uses the default when the key is unset', () => {
    expect(pipe.transform({}, 'a', false)).toBe(false);
    expect(pipe.transform({}, 'a', true)).toBe(true);
  });
  it('lets an explicit value override either default', () => {
    expect(pipe.transform({ a: true }, 'a', false)).toBe(true);
    expect(pipe.transform({ a: false }, 'a', true)).toBe(false);
  });
  it('opens everything when allOpen is set', () => {
    expect(pipe.transform({ a: false }, 'a', false, true)).toBe(true);
  });
});
