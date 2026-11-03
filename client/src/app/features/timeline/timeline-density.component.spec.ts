import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { TimelineDensityComponent } from './timeline-density.component';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineFiltersService } from './timeline-filters.service';
import { densityBuckets, densityRange, timelineWindow, type DensityResponse } from './timeline-density.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';

@Component({ template: '' }) class OtherPage {}
const years = { years: [{ year: '2020', count: 100 }, { year: '2019', count: 1 }, { year: '2021', count: 0 }] };

describe('Timeline date density', () => {
  it('clips valid calendar periods to the requested dates and leaves invalid years alone', () => {
    expect(timelineWindow('bad', '2', '2024-02-10', '2024-02-20'))
      .toEqual({ from: '2024-02-10', to: '2024-02-20' });
    expect(timelineWindow('2024', '2', '', ''))
      .toEqual({ from: '2024-02-01', to: '2024-02-29' });
    expect(timelineWindow('2024', '13', '2024-04-01', '2024-10-31'))
      .toEqual({ from: '2024-04-01', to: '2024-10-31' });
    expect(timelineWindow('2024', '02', '2024-02-10', '2024-02-20'))
      .toEqual({ from: '2024-02-10', to: '2024-02-20' });
    expect(timelineWindow('2024', '2', '2023-01-01', '2025-01-01'))
      .toEqual({ from: '2024-02-01', to: '2024-02-29' });
  });

  async function render(openOnArrival = false) {
    const api = { get: vi.fn().mockReturnValue(of(years)) };
    const auth = { status: signal({ user_id: 'alice' }), token: 'a' };
    TestBed.configureTestingModule({ imports: [TimelineDensityComponent, TimelineYearsComponent], providers: [
      provideRouter([{ path: 'timeline', component: OtherPage }, { path: 'elsewhere', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }), photos: signal([]) } },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    const router = TestBed.inject(Router); await router.navigateByUrl(openOnArrival ? '/timeline?density=1' : '/timeline');
    const fixture = TestBed.createComponent(TimelineDensityComponent); fixture.detectChanges(); await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    const settle = async () => { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); };
    const open = async () => { const details = root.querySelector('details')!; details.open = true; details.dispatchEvent(new Event('toggle')); await settle(); const range = [...root.querySelectorAll<HTMLButtonElement>('button')].find(row => row.textContent?.includes('timeline.select_range')); range?.click(); await settle(); };
    const bars = () => [...root.querySelectorAll<HTMLButtonElement>('[aria-describedby] > button')];
    const button = (key: string) => [...root.querySelectorAll<HTMLButtonElement>('button')].find(row => row.textContent?.includes(key))!;
    return { fixture, root, api, auth, router, settle, open, bars, button, filters: TestBed.inject(TimelineFiltersService) };
  }

  it('opens the actual disclosure on a drill-down arrival', async () => {
    const v = await render(true);
    expect(v.root.querySelector('details')!.open).toBe(true);
    expect(v.bars().length).toBeGreaterThan(0);
    v.fixture.destroy();
  });

  it('drills into a year and month directly in browse mode', async () => {
    const v = await render(); const navigate = vi.spyOn(v.router, 'navigate').mockResolvedValue(true);
    await v.open(); v.button('timeline.select_range').click(); await v.settle();
    v.bars()[0].click(); await v.settle();
    expect(navigate).toHaveBeenCalledWith(['/timeline', '2019'], { queryParams: { density: '1' } });
    v.fixture.componentRef.setInput('year', '2019');
    v.api.get.mockReturnValue(of({ months: [{ month: '2019-02', count: 2 }] })); await v.settle();
    v.bars()[1].click(); await v.settle();
    expect(navigate).toHaveBeenLastCalledWith(['/timeline', '2019', '2'], { queryParams: { density: '1' } });
    v.fixture.destroy();
  });

  it('fetches only when expanded and applies the exact selected range without changing filters while drafting', async () => {
    const v = await render(); expect(v.api.get).not.toHaveBeenCalled(); await v.open();
    expect(v.api.get).toHaveBeenCalledExactlyOnceWith('/timeline/years', expect.objectContaining({ hide_bursts: '1' }));
    expect(v.bars()).toHaveLength(3); v.bars()[0].click(); v.bars()[2].click(); await v.settle();
    expect(v.filters.dateFrom()).toBe(''); expect(v.filters.dateTo()).toBe('');
    expect(v.root.textContent).toContain('01/01/2019 – 31/12/2021');
    expect(v.bars().every(row => row.getAttribute('aria-pressed') === 'true')).toBe(true);
    v.button('timeline.apply_range').click(); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31'); v.fixture.destroy();
  });

  it('changes only the chart scale, retaining actual counts and the chosen boundary', async () => {
    const v = await render(); await v.open(); v.bars()[0].click(); await v.settle();
    const before = v.bars()[0].querySelector<HTMLElement>('span > span')!.style.height;
    v.root.querySelector<HTMLInputElement>('input[type=checkbox]')!.dispatchEvent(new Event('change')); await v.settle();
    const after = v.bars()[0].querySelector<HTMLElement>('span > span')!.style.height;
    expect(parseFloat(after)).toBeGreaterThan(parseFloat(before));
    expect(v.bars()[0].getAttribute('aria-label')).toContain('"count":1');
    expect(v.bars()[0].getAttribute('aria-pressed')).toBe('true'); expect(v.api.get).toHaveBeenCalledTimes(1); v.fixture.destroy();
  });

  it('shows zero-count days and leap day in the selected month', async () => {
    const v = await render(); v.fixture.componentRef.setInput('year', '2024'); v.fixture.componentRef.setInput('month', '2');
    v.api.get.mockReturnValueOnce(of({ dates: [{ date: '2024-02-28', count: 3 }] })); await v.open();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline/dates', expect.objectContaining({ year: 2024, month: 2 }));
    expect(v.bars()).toHaveLength(29); expect(v.bars()[28].getAttribute('aria-label')).toContain('"period":"2024-02-29","count":0');
    v.bars()[28].click(); await v.settle(); v.button('timeline.apply_range').click(); await v.settle();
    expect(v.filters.dateFrom()).toBe('2024-02-29'); expect(v.filters.dateTo()).toBe('2024-02-29'); v.fixture.destroy();
  });

  it('offers ISO weeks with exact clipped year-boundary dates and applies only the selected period', async () => {
    const v = await render(); v.fixture.componentRef.setInput('year', '2021');
    v.api.get.mockReturnValueOnce(of({ months: [] })); await v.open();
    v.api.get.mockReturnValue(of({ dates: [{ date: '2021-01-01', count: 1 }, { date: '2021-01-03', count: 3 }, { date: '2021-01-04', count: 4 }] }));
    const select = v.root.querySelector<HTMLSelectElement>('[data-density-unit]')!;
    select.value = 'week'; select.dispatchEvent(new Event('change')); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline/dates', expect.objectContaining({ year: 2021 }));
    expect(v.bars()).toHaveLength(53);
    expect(v.bars()[0].textContent).toContain('2020-W53');
    expect(v.bars()[0].getAttribute('aria-label')).toContain('"period":"01/01/2021 – 03/01/2021","count":4');
    v.bars()[0].click(); await v.settle();
    expect(v.filters.dateFrom()).toBe(''); expect(v.filters.dateTo()).toBe('');
    expect(v.button('timeline.explore_period')).toBeUndefined();
    v.button('timeline.apply_range').click(); await v.settle();
    expect(v.filters.dateFrom()).toBe('2021-01-01'); expect(v.filters.dateTo()).toBe('2021-01-03');
    v.fixture.destroy();
  });

  it('restores year exploration after returning from weekly density to all years', async () => {
    const v = await render(); v.fixture.componentRef.setInput('year', '2021');
    await v.open();
    const select = v.root.querySelector<HTMLSelectElement>('[data-density-unit]')!;
    select.value = 'week'; select.dispatchEvent(new Event('change')); await v.settle();
    v.fixture.componentRef.setInput('year', ''); await v.settle();
    expect(v.root.querySelector('[data-density-unit]')).toBeNull();
    v.bars()[0].click(); await v.settle();
    expect(v.button('timeline.explore_period')).toBeDefined();
    v.fixture.destroy();
  });

  it('clips partial week counts and empty weeks to the typed range, including leap day', () => {
    const rows = densityBuckets({ dates: [{ date: '2024-02-28', count: 2 }, { date: '2024-02-29', count: 3 }, { date: '2024-02-01', count: 99 }] }, '2024', '2', { unit: 'week', from: '2024-02-20', to: '2024-02-29' });
    expect(rows).toEqual([
      { key: '2024-W08', label: '2024-W08', from: '2024-02-20', to: '2024-02-25', count: 0 },
      { key: '2024-W09', label: '2024-W09', from: '2024-02-26', to: '2024-02-29', count: 5 },
    ]);
  });

  it('cancels reads on navigation and clears prior-account counts and draft selection', async () => {
    const v = await render(); const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending); await v.open();
    expect(pending.observed).toBe(true); await v.router.navigateByUrl('/elsewhere'); await v.settle();
    expect(pending.observed).toBe(false); pending.next(years); expect(v.bars()).toHaveLength(0);
    v.auth.status.set({ user_id: 'bob' }); v.auth.token = 'b'; await v.settle(); expect(v.bars()).toHaveLength(0); v.fixture.destroy();
  });

  it('reports a failed count read and retries without presenting an empty library', async () => {
    const v = await render(); v.api.get.mockReturnValueOnce(throwError(() => new Error('offline'))); await v.open();
    expect(v.root.querySelector('[role=alert]')).not.toBeNull(); expect(v.root.textContent).not.toContain('timeline.empty');
    v.button('timeline.retry').click(); await v.settle(); expect(v.bars()).toHaveLength(3); v.fixture.destroy();
  });

  it('refuses a draft after token rotation and lets Escape close the owned disclosure', async () => {
    const v = await render(); await v.open(); v.bars()[0].click(); await v.settle();
    v.auth.token = 'b'; v.button('timeline.apply_range').click();
    expect(v.filters.dateFrom()).toBe(''); expect(v.filters.dateTo()).toBe('');
    const details = v.root.querySelector('details')!;
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    details.dispatchEvent(escape); await v.settle();
    expect(escape.defaultPrevented).toBe(true); expect(details.open).toBe(false); v.fixture.destroy();
  });

  it('clears stale Calendar reads on account changes and provides real error/retry state', async () => {
    const v = await render(); const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending);
    const calendar = TestBed.createComponent(TimelineYearsComponent); calendar.detectChanges(); await calendar.whenStable();
    expect(pending.observed).toBe(true);
    v.api.get.mockReturnValueOnce(of({ years: [{ year: '2026', count: 3, hero_photo_path: '/bob.jpg' }] }));
    v.auth.status.set({ user_id: 'bob' }); v.auth.token = 'b'; calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges();
    expect(pending.observed).toBe(false); pending.next(years);
    expect(calendar.nativeElement.querySelector('img')?.getAttribute('alt')).toBe('2026');
    v.api.get.mockReturnValueOnce(throwError(() => new Error('offline'))); v.filters.dateFrom.set('2026-01-01');
    calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges();
    expect(calendar.nativeElement.querySelector('[role=alert]')).not.toBeNull();
    expect(calendar.nativeElement.textContent).not.toContain('timeline.empty');
    v.api.get.mockReturnValueOnce(of({ years: [{ year: '2026', count: 1, hero_photo_path: '/bob.jpg' }] }));
    calendar.nativeElement.querySelector('button').click(); calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges();
    expect(calendar.nativeElement.querySelector('[role=alert]')).toBeNull(); expect(calendar.nativeElement.querySelector('img')).not.toBeNull();
    calendar.destroy(); v.fixture.destroy();
  });
});

describe('Timeline density date boundaries', () => {
  it('uses complete calendar months and sorts a reversed range without timezone shifts', () => {
    const months = densityBuckets({ months: [{ month: '2024-02', count: 3 }] }, '2024', '');
    expect(months).toHaveLength(12); expect(months[1]).toMatchObject({ from: '2024-02-01', to: '2024-02-29', count: 3 });
    expect(months[0].count).toBe(0);
    expect(densityRange(months[2], months[1])).toEqual({ from: '2024-02-01', to: '2024-03-31' });
  });
});
