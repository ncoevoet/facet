import { computeRangeFilterUpdate } from './range-filter';
import { AdditionalFilterDef } from '../models/filter-def.model';

const def: AdditionalFilterDef = {
  id: 'iso',
  labelKey: 'filters.iso',
  sectionKey: 'camera',
  minKey: 'iso_min',
  maxKey: 'iso_max',
  sliderMin: 100,
  sliderMax: 6400,
  step: 100,
  spanWidth: 'col-span-2',
};

describe('computeRangeFilterUpdate', () => {
  describe('min side', () => {
    it('sets the min key to the stringified value', () => {
      expect(computeRangeFilterUpdate(def, 'min', 800, undefined)).toEqual({
        key: 'iso_min',
        value: '800',
      });
    });

    it('clears the value (empty string) when value equals sliderMin boundary', () => {
      expect(computeRangeFilterUpdate(def, 'min', 100, undefined)).toEqual({
        key: 'iso_min',
        value: '',
      });
    });

    it('keeps a min value distinct from the boundary even with no current min', () => {
      expect(computeRangeFilterUpdate(def, 'min', 200, undefined)).toEqual({
        key: 'iso_min',
        value: '200',
      });
    });
  });

  describe('max side with a current min value present', () => {
    it('sets the max key to the stringified value', () => {
      expect(computeRangeFilterUpdate(def, 'max', 3200, '800')).toEqual({
        key: 'iso_max',
        value: '3200',
      });
    });

    it('clears the value when value equals sliderMax boundary', () => {
      expect(computeRangeFilterUpdate(def, 'max', 6400, '800')).toEqual({
        key: 'iso_max',
        value: '',
      });
    });

    it('treats a truthy boolean currentMinValue as present (stays on max side)', () => {
      expect(computeRangeFilterUpdate(def, 'max', 3200, true)).toEqual({
        key: 'iso_max',
        value: '3200',
      });
    });
  });

  describe('max side with NO current min value (redirects to min)', () => {
    it('writes to the min key instead of the max key', () => {
      // Dragging the max handle first while min is unset assigns to min.
      expect(computeRangeFilterUpdate(def, 'max', 3200, undefined)).toEqual({
        key: 'iso_min',
        value: '3200',
      });
    });

    it('uses sliderMin as the clear-boundary after redirecting to min', () => {
      // value === sliderMin clears; sliderMax would NOT clear here.
      expect(computeRangeFilterUpdate(def, 'max', 100, undefined)).toEqual({
        key: 'iso_min',
        value: '',
      });
      expect(computeRangeFilterUpdate(def, 'max', 6400, undefined)).toEqual({
        key: 'iso_min',
        value: '6400',
      });
    });

    it('redirects to min when currentMinValue is an empty string (falsy)', () => {
      expect(computeRangeFilterUpdate(def, 'max', 3200, '')).toEqual({
        key: 'iso_min',
        value: '3200',
      });
    });

    it('redirects to min when currentMinValue is false (falsy)', () => {
      expect(computeRangeFilterUpdate(def, 'max', 3200, false)).toEqual({
        key: 'iso_min',
        value: '3200',
      });
    });
  });

  it('handles a zero value (stringified, not treated as missing)', () => {
    const zeroDef: AdditionalFilterDef = { ...def, sliderMin: -10, sliderMax: 10 };
    expect(computeRangeFilterUpdate(zeroDef, 'min', 0, undefined)).toEqual({
      key: 'iso_min',
      value: '0',
    });
  });

  it('handles negative boundary values', () => {
    const negDef: AdditionalFilterDef = { ...def, sliderMin: -5, sliderMax: 5 };
    expect(computeRangeFilterUpdate(negDef, 'min', -5, undefined)).toEqual({
      key: 'iso_min',
      value: '',
    });
    expect(computeRangeFilterUpdate(negDef, 'max', 5, '-3')).toEqual({
      key: 'iso_max',
      value: '',
    });
  });
});
