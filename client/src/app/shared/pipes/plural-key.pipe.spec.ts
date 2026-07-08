import { PluralKeyPipe } from './plural-key.pipe';

describe('PluralKeyPipe', () => {
  const pipe = new PluralKeyPipe();

  it('returns the singular key when count is 1', () => {
    expect(pipe.transform(1, 'proofing.picks_count', 'proofing.picks_count_plural')).toBe('proofing.picks_count');
  });

  it('returns the plural key when count is not 1', () => {
    expect(pipe.transform(0, 'proofing.picks_count', 'proofing.picks_count_plural')).toBe('proofing.picks_count_plural');
    expect(pipe.transform(2, 'proofing.picks_count', 'proofing.picks_count_plural')).toBe('proofing.picks_count_plural');
  });
});
