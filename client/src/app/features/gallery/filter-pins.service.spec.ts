import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';
import { FilterPinsService, FILTER_PIN_LIMIT } from './filter-pins.service';

describe('FilterPinsService', () => {
  const allowed = Array.from({ length: 8 }, (_, i) => `metric_${i}`);
  const owner = signal('1|alice');
  const key = (identity: string) => 'facet_filter_pins:' + encodeURIComponent(identity);
  beforeEach(() => {
    owner.set('1|alice');
    for (const identity of ['1|alice', '1|bob', '0|']) localStorage.removeItem(key(identity));
    TestBed.configureTestingModule({ providers: [{ provide: AuthService, useValue: { identity: owner } }] });
  });
  afterEach(() => { vi.restoreAllMocks(); TestBed.resetTestingModule(); });

  it('bounds valid unique control IDs and persists no values or foreign fields', () => {
    localStorage.setItem(key(owner()), JSON.stringify(['unknown', allowed[0], allowed[0], 3, ...allowed.slice(1)]));
    const service = TestBed.inject(FilterPinsService);
    expect(service.ids(allowed)).toEqual(allowed.slice(0, FILTER_PIN_LIMIT));
    expect(service.toggle(allowed[6], allowed)).toBe(false);
    expect(service.toggle('unknown', allowed)).toBe(false);
    expect(service.toggle(allowed[0], allowed)).toBe(true);
    expect(service.toggle(allowed[6], allowed)).toBe(true);
    expect(JSON.parse(localStorage.getItem(key(owner()))!)).toEqual([...allowed.slice(1, 6), allowed[6]]);
  });

  it('isolates accounts immediately, restores each placement, and never persists anonymous choices', () => {
    const service = TestBed.inject(FilterPinsService);
    service.toggle(allowed[0], allowed);
    owner.set('1|bob'); expect(service.ids(allowed)).toEqual([]);
    service.toggle(allowed[1], allowed);
    owner.set('1|alice'); expect(service.ids(allowed)).toEqual([allowed[0]]);
    owner.set('0|'); expect(service.ids(allowed)).toEqual([]);
    service.toggle(allowed[2], allowed);
    expect(service.ids(allowed)).toEqual([allowed[2]]);
    expect(localStorage.getItem(key('0|'))).toBeNull();
    owner.set('1|bob'); expect(service.ids(allowed)).toEqual([allowed[1]]);
  });

  it('ignores invalid storage and keeps a tab-local choice when persistence is refused', () => {
    localStorage.setItem(key(owner()), '{bad json');
    const service = TestBed.inject(FilterPinsService);
    expect(service.ids(allowed)).toEqual([]);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
    expect(service.toggle(allowed[0], allowed)).toBe(true);
    expect(service.ids(allowed)).toEqual([allowed[0]]);
  });
});
