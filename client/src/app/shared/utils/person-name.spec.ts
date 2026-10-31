import { isUnnamedPerson, personNameKey, sameName } from './person-name';

describe('person name folding', () => {
  it('ignores case and outer spaces, like casefold', () => {
    expect(sameName(' Peter Salem', 'peter salem ')).toBe(true);
    expect(sameName('ÉLODIE', 'élodie')).toBe(true);
  });

  it('folds ß to ss, as casefold does', () => {
    expect(sameName('straße', 'STRASSE')).toBe(true);
    expect(personNameKey('Straße')).toBe('strasse');
  });

  it('does not apply NFKC, which casefold does not either', () => {
    // A full-width "Ａ" is not folded to "a" by casefold.
    expect(sameName('Ａnna', 'anna')).toBe(false);
  });

  it('never matches an empty name', () => {
    expect(sameName('  ', '  ')).toBe(false);
    expect(sameName(null, 'x')).toBe(false);
  });
});

describe('isUnnamedPerson', () => {
  it('is true for null, undefined, empty and space-only names', () => {
    expect(isUnnamedPerson(null)).toBe(true);
    expect(isUnnamedPerson(undefined)).toBe(true);
    expect(isUnnamedPerson('')).toBe(true);
    expect(isUnnamedPerson('   ')).toBe(true);
  });

  it('is false for a real name, and for tab-only names exactly as the SQL TRIM is', () => {
    expect(isUnnamedPerson('Ann')).toBe(false);
    expect(isUnnamedPerson(' Ann ')).toBe(false);
    expect(isUnnamedPerson('\t')).toBe(false);
  });
});
