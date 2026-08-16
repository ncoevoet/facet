import { TestBed } from '@angular/core/testing';
import { HISTOGRAM_MODE_KEYS, HistogramPreferencesService } from './histogram-preferences.service';

describe('HistogramPreferencesService', () => {
  let service: HistogramPreferencesService;

  beforeEach(() => {
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.detail);
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.tooltip);
    TestBed.configureTestingModule({});
    service = TestBed.inject(HistogramPreferencesService);
  });

  afterEach(() => {
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.detail);
    localStorage.removeItem(HISTOGRAM_MODE_KEYS.tooltip);
  });

  it('starts with no persisted choice on either surface', () => {
    expect(service.mode('detail')).toBeNull();
    expect(service.mode('tooltip')).toBeNull();
  });

  it('persists a surface choice under its own localStorage key', () => {
    service.setMode('detail', 'r');
    expect(localStorage.getItem(HISTOGRAM_MODE_KEYS.detail)).toBe('r');
    expect(localStorage.getItem(HISTOGRAM_MODE_KEYS.tooltip)).toBeNull();
  });

  it('setting the detail surface does not change what the tooltip surface resolves to', () => {
    service.setMode('detail', 'r');
    expect(service.mode('tooltip')).toBeNull();
  });

  it('setting the tooltip surface does not change what the detail surface resolves to', () => {
    service.setMode('tooltip', 'g');
    expect(service.mode('detail')).toBeNull();
  });

  it('the two surfaces can hold different modes at the same time', () => {
    service.setMode('detail', 'rgb');
    service.setMode('tooltip', 'luma');
    expect(service.mode('detail')).toBe('rgb');
    expect(service.mode('tooltip')).toBe('luma');
  });

  it('loads each surface\'s own persisted value on construction', () => {
    localStorage.setItem(HISTOGRAM_MODE_KEYS.detail, 'b');
    localStorage.setItem(HISTOGRAM_MODE_KEYS.tooltip, 'luma');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const fresh = TestBed.inject(HistogramPreferencesService);

    expect(fresh.mode('detail')).toBe('b');
    expect(fresh.mode('tooltip')).toBe('luma');
  });

  it('degrades a stale/unrecognised stored value to null (config default applies) instead of rendering nothing', () => {
    localStorage.setItem(HISTOGRAM_MODE_KEYS.detail, 'sepia');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const fresh = TestBed.inject(HistogramPreferencesService);

    expect(fresh.mode('detail')).toBeNull();
  });
});
