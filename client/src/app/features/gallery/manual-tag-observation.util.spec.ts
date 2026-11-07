import { observeManualTags } from './manual-tag-observation.util';

describe('manual tag observations', () => {
  it('counts each tag once per photo and includes photos without tags', () => {
    expect(observeManualTags([{ manual_tags: ['coast', 'coast'] }, {}, { manual_tags: ['coast', 'sun'] }]))
      .toEqual({ photos: 3, tags: [{ tag: 'coast', count: 2 }, { tag: 'sun', count: 1 }], overflow: 0 });
  });

  it('bounds the displayed list while counting omitted distinct tags', () => {
    const tags = Array.from({ length: 25 }, (_, index) => `tag-${String(index).padStart(2, '0')}`);
    const observed = observeManualTags([{ manual_tags: tags }, { manual_tags: ['tag-24'] }]);
    expect(observed.tags).toHaveLength(20);
    expect(observed.tags[0]).toEqual({ tag: 'tag-24', count: 2 });
    expect(observed.overflow).toBe(5);
  });
});
