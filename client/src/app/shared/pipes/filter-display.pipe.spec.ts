import { FilterDisplayPipe } from './filter-display.pipe';
import { AdditionalFilterDef } from '../models/filter-def.model';

describe('FilterDisplayPipe', () => {
  const pipe = new FilterDisplayPipe();

  const baseDef: AdditionalFilterDef = {
    id: 'score',
    labelKey: 'ui.filters.score',
    sectionKey: 'scores',
    minKey: 'min_score',
    maxKey: 'max_score',
    sliderMin: 0,
    sliderMax: 10,
    step: 0.1,
    spanWidth: 'col-span-2',
  };

  it('shows range from filter values', () => {
    const filters = { min_score: '3', max_score: '8' };
    expect(pipe.transform(filters, baseDef)).toBe('3-8');
  });

  it('falls back to slider min/max when filters are empty', () => {
    const filters = { min_score: '', max_score: '' };
    expect(pipe.transform(filters, baseDef)).toBe('0-10');
  });

  it('includes prefix and suffix when defined', () => {
    const def = { ...baseDef, displayPrefix: 'ISO ', displaySuffix: '+' };
    const filters = { min_score: '100', max_score: '3200' };
    expect(pipe.transform(filters, def)).toBe('ISO 100-3200+');
  });

  it('handles missing prefix/suffix gracefully', () => {
    const filters = { min_score: '5', max_score: '10' };
    expect(pipe.transform(filters, baseDef)).toBe('5-10');
  });
});
