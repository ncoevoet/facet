import { restoreAlbumRuleFields } from './album-rules.util';
import { DEFAULT_FILTERS } from './gallery-filters.util';

describe('restoreAlbumRuleFields', () => {
  it.each(['null', '[]', 'false', '"text"', '{"unexpected":true}', '{"camera":42}'])(
    'refuses unsupported saved rules without changing the working filters: %s', json => {
      const current = { ...DEFAULT_FILTERS, camera: 'Working camera' };
      expect(() => restoreAlbumRuleFields(current, json)).toThrow();
      expect(current.camera).toBe('Working camera');
    });

  it('restores saved rules and clears omitted persistable fields', () => {
    const restored = restoreAlbumRuleFields({ ...DEFAULT_FILTERS, camera: 'Working camera' }, '{"lens":"Saved lens"}');
    expect(restored.camera).toBe(DEFAULT_FILTERS.camera);
    expect(restored.lens).toBe('Saved lens');
  });
});
