import { WEIGHT_ICONS } from '../../features/comparison/comparison.pipes';
import { SECTION_ICONS } from '../../features/gallery/gallery-filter-sidebar.component';
import { FEATURE_MARK, MarkTonePipe } from './mark-tone.pipe';
import { SORT_ICONS } from './sort-option-icon.pipe';

describe('icon tables that draw the feature mark', () => {
  const pipe = new MarkTonePipe();
  const tables: Record<string, Readonly<Record<string, string>>> = {
    SORT_ICONS,
    WEIGHT_ICONS,
    SECTION_ICONS,
  };

  for (const [name, table] of Object.entries(tables)) {
    it(`${name} colours every ${FEATURE_MARK} entry`, () => {
      const marked = Object.keys(table).filter(key => table[key] === FEATURE_MARK);
      expect(marked.length).toBeGreaterThan(0);
      for (const key of marked) {
        expect(pipe.transform(key), `${name}.${key}`).not.toBe('');
      }
    });
  }
});
