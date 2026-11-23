import { sortLabelKey, sortOptionLabelKey } from './sort-label';

describe('sortLabelKey', () => {
  it('names sorts that have no sort_options entry', () => {
    expect(sortLabelKey('relevance')).toBe('gallery.sort_relevance');
    expect(sortLabelKey('learned_score')).toBe('gallery.sort_my_taste');
    expect(sortLabelKey('top_picks_score')).toBe('photo_types.top_picks');
    expect(sortLabelKey('filename')).toBe('filter_labels.search');
  });

  it('falls back to the sort_options table', () => {
    expect(sortLabelKey('aggregate')).toBe('sort_options.aggregate');
  });

  it('names the library for Date Added inside an album only', () => {
    expect(sortLabelKey('date_added')).toBe('sort_options.date_added');
    expect(sortLabelKey('date_added', true)).toBe('sort_options.date_added_library');
    expect(sortOptionLabelKey('date_added', true)).toBe('sort_options.date_added_library');
    expect(sortOptionLabelKey('aggregate', true)).toBe('sort_options.aggregate');
    expect(sortLabelKey('top_picks_score', true)).toBe('photo_types.top_picks');
  });
});
