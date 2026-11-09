import { Component, signal, type OutputEmitterRef } from '@angular/core';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { TimelineDensityComponent } from './timeline-density.component';
import { TimelineYearsComponent } from './timeline-years.component';
import { TimelineFiltersService } from './timeline-filters.service';
import { timelineDayQuery } from './timeline-day-query.pipe';
import { densityBuckets, densityRange, timelineWindow, type DensityResponse } from './timeline-density.util';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { makePhoto } from '../../../testing/photo.fixture';
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

  async function render(inputs: Record<string, unknown> = {}) {
    const api = { get: vi.fn().mockReturnValue(of(years)) };
    const auth = { status: signal({ user_id: 'alice' }), token: 'a' };
    const photos = signal([makePhoto({ path: '/photo.jpg', date_taken: '2020-01-01' })]);
    const timelineMembershipRevision = signal(0);
    const loading = signal(false);
    TestBed.configureTestingModule({ imports: [TimelineDensityComponent, TimelineYearsComponent], providers: [
      provideRouter([{ path: 'timeline', component: OtherPage }, { path: 'elsewhere', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({ hide_bursts: '1' }), photos, timelineMembershipRevision, loading } },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    const router = TestBed.inject(Router); await router.navigateByUrl('/timeline');
    const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const fixture = TestBed.createComponent(TimelineDensityComponent);
    for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
    const totals: (number | null)[] = [];
    (fixture.componentInstance.total as OutputEmitterRef<number | null>).subscribe(value => totals.push(value));
    fixture.detectChanges(); await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    const settle = async () => { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); };
    const bars = () => [...root.querySelectorAll<HTMLButtonElement>('[data-density-key]')];
    const button = (key: string) => [...root.querySelectorAll<HTMLButtonElement>('button')].find(row => row.textContent?.includes(key) || row.getAttribute('aria-label')?.includes(key))!;
    const key = (target: Element, name: string, init: KeyboardEventInit = {}) => {
      const event = new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event); return event;
    };
    const pointer = (type: string, target: Element, init: Record<string, unknown> = {}) => target.dispatchEvent(
      new (globalThis.PointerEvent ?? MouseEvent)(type, { bubbles: true, cancelable: true, button: 0, buttons: 1, pointerType: 'mouse', clientX: 1, clientY: 1, ...init } as PointerEventInit));
    const under = (target: Element | null) => { (document as unknown as { elementFromPoint: unknown }).elementFromPoint = vi.fn(() => target); };
    return { fixture, root, api, auth, photos, timelineMembershipRevision, loading, router, navigate, totals, settle, bars, button, key, pointer, under, filters: TestBed.inject(TimelineFiltersService) };
  }

  afterEach(() => { delete (document as unknown as { elementFromPoint?: unknown }).elementFromPoint; });

  it('renders the strip at once, with no disclosure and no query parameter', async () => {
    const v = await render();
    expect(v.root.querySelector('details')).toBeNull();
    expect(v.api.get).toHaveBeenCalledExactlyOnceWith('/timeline/years', expect.objectContaining({ hide_bursts: '1' }), expect.anything());
    expect(v.api.get.mock.calls[0][2].get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
    expect(v.bars()).toHaveLength(3);
    v.fixture.destroy();
  });

  it('draws bars filling their bucket, with a label and a tooltip count but no visible count line', async () => {
    const v = await render();
    v.api.get.mockReturnValue(of({ years: [{ year: '2020', count: 12345 }] })); v.fixture.componentRef.setInput('year', ''); v.fixture.componentRef.setInput('month', '');
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    const bar = v.bars()[0];
    expect(bar.textContent?.trim()).toBe('2020');
    expect(bar.querySelector('.max-w-12')).toBeNull();
    expect(bar.className).toContain('min-w-11');
    const tip = v.fixture.debugElement.queryAll(By.directive(MatTooltip))[0].injector.get(MatTooltip);
    expect(tip.message).toContain('"count":"12,345"');
    expect(bar.getAttribute('aria-label')).toContain('"count":12345');
    expect(v.root.querySelector('[role=group]')!.getAttribute('aria-label')).toBe('timeline.density_years');
    expect(v.root.textContent).not.toContain('timeline.density_years');
    v.fixture.destroy();
  });

  it('renders nothing when hidden yet still reads the data and reports the total', async () => {
    const v = await render({ visible: false });
    expect(v.api.get).toHaveBeenCalledTimes(1);
    expect(v.bars()).toHaveLength(0); expect(v.root.querySelector('[role=group]')).toBeNull();
    expect(v.totals.at(-1)).toBe(101);
    v.fixture.componentRef.setInput('visible', true); await v.settle();
    expect(v.bars()).toHaveLength(3); expect(v.api.get).toHaveBeenCalledTimes(1);
    v.fixture.destroy();
  });

  it('emits the summed bucket counts, and null while loading or after a failure', async () => {
    const v = await render(); expect(v.totals.at(-1)).toBe(101);
    const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending);
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(v.totals.at(-1)).toBeNull(); pending.next({ years: [{ year: '2020', count: 7 }] }); await v.settle();
    expect(v.totals.at(-1)).toBe(7);
    v.api.get.mockReturnValueOnce(throwError(() => new Error('offline')));
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(v.totals.at(-1)).toBeNull(); expect(v.root.querySelector('[role=alert]')).not.toBeNull();
    v.fixture.destroy();
  });

  it('preserves a keyboard draft after review marks, but refreshes changed membership', async () => {
    const v = await render();
    v.bars()[0].focus(); v.key(v.bars()[0], 'ArrowRight', { shiftKey: true }); await v.settle();
    expect(v.bars()[0].getAttribute('aria-pressed')).toBe('true');
    v.api.get.mockClear();
    v.photos.update(rows => rows.map(photo => ({ ...photo, star_rating: 4, is_favorite: true, is_kept: true })));
    await v.settle();
    expect(v.api.get).not.toHaveBeenCalled();
    expect(v.bars()[0].getAttribute('aria-pressed')).toBe('true');
    v.photos.update(rows => rows.map(photo => ({ ...photo, date_taken: '2021-01-01' })));
    await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(1);
    expect(v.bars().every(bar => bar.getAttribute('aria-pressed') === 'false')).toBe(true);
    v.api.get.mockClear();
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(1);
    v.fixture.destroy();
  });

  it('keeps the draft through the temporary Gallery clear and reads once at settlement', async () => {
    const v = await render();
    v.bars()[0].focus(); v.key(v.bars()[0], 'ArrowRight', { shiftKey: true }); await v.settle();
    const rows = v.photos(); v.api.get.mockClear();
    v.loading.set(true); v.photos.set([]); await v.settle();
    expect(v.api.get).not.toHaveBeenCalled(); expect(v.bars()[0].getAttribute('aria-pressed')).toBe('true');
    v.photos.set(rows); await v.settle(); expect(v.api.get).not.toHaveBeenCalled();
    v.timelineMembershipRevision.update(value => value + 1); v.loading.set(false); await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(1); v.fixture.destroy();
  });

  it('drills a year, a month and a day on a plain click, with no query parameter', async () => {
    const v = await render();
    v.bars()[0].click(); await v.settle();
    expect(v.navigate).toHaveBeenLastCalledWith(['/timeline', '2019']);
    v.fixture.componentRef.setInput('year', '2019');
    v.api.get.mockReturnValue(of({ months: [{ month: '2019-02', count: 2 }] })); await v.settle();
    v.bars()[1].click(); await v.settle();
    expect(v.navigate).toHaveBeenLastCalledWith(['/timeline', '2019', '2']);
    v.fixture.componentRef.setInput('year', '2024'); v.fixture.componentRef.setInput('month', '2');
    v.api.get.mockReturnValue(of({ dates: [{ date: '2024-02-28', count: 3 }] })); await v.settle();
    v.bars()[28].click(); await v.settle();
    expect(v.navigate).toHaveBeenLastCalledWith(['/'], { queryParams: timelineDayQuery('2024-02-29', { hide_bursts: '1' } as never) });
    expect(v.filters.dateFrom()).toBe('');
    v.fixture.destroy();
  });

  it('applies a week as the date range on a plain click, without navigating', async () => {
    const v = await render(); v.fixture.componentRef.setInput('year', '2021'); await v.settle();
    v.api.get.mockReturnValue(of({ dates: [{ date: '2021-01-01', count: 1 }, { date: '2021-01-03', count: 3 }, { date: '2021-01-04', count: 4 }] }));
    v.button('timeline.density_weeks').click(); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline/dates', expect.objectContaining({ year: 2021 }), expect.anything());
    expect(v.bars()).toHaveLength(53);
    expect(v.bars()[0].textContent).toContain('2020-W53');
    expect(v.bars()[0].getAttribute('aria-label')).toContain('"period":"01/01/2021 – 03/01/2021","count":4');
    v.navigate.mockClear(); v.bars()[0].click(); await v.settle();
    expect(v.filters.dateFrom()).toBe('2021-01-01'); expect(v.filters.dateTo()).toBe('2021-01-03');
    expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('applies a mouse drag across buckets as the range, without navigating or drilling on release', async () => {
    const v = await render(); const bars = v.bars();
    v.pointer('pointerdown', bars[0]);
    v.under(bars[1]); v.pointer('pointermove', bars[1]); await v.settle();
    v.under(bars[2]); v.pointer('pointermove', bars[2]); await v.settle();
    expect(bars.every(row => row.getAttribute('aria-pressed') === 'true')).toBe(true);
    expect(v.filters.dateFrom()).toBe('');
    v.pointer('pointerup', bars[2]); bars[2].click(); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('lets a drag end outside the strip and drills normally on the next plain click', async () => {
    const v = await render(); const bars = v.bars();
    v.pointer('pointerdown', bars[0]); v.under(bars[1]); v.pointer('pointermove', bars[1]);
    v.under(null); v.pointer('pointerup', document.body); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2020-12-31');
    v.pointer('pointerdown', bars[2]); v.pointer('pointerup', bars[2]); bars[2].click(); await v.settle();
    expect(v.navigate).toHaveBeenCalledWith(['/timeline', '2021']);
    v.fixture.destroy();
  });

  it('does not drag with touch pointers: a tap drills', async () => {
    const v = await render(); const bars = v.bars();
    v.pointer('pointerdown', bars[0], { pointerType: 'touch' }); v.under(bars[2]); v.pointer('pointermove', bars[2], { pointerType: 'touch' });
    v.pointer('pointerup', bars[2], { pointerType: 'touch' }); await v.settle();
    expect(v.filters.dateFrom()).toBe(''); expect(bars.every(row => row.getAttribute('aria-pressed') === 'false')).toBe(true);
    bars[0].click(); await v.settle();
    expect(v.navigate).toHaveBeenCalledWith(['/timeline', '2019']);
    v.fixture.destroy();
  });

  it('applies the range from the last clicked bucket on Shift+click', async () => {
    const v = await render(); const bars = v.bars();
    bars[0].click(); await v.settle();
    bars[2].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey: true })); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    expect(v.navigate).toHaveBeenCalledTimes(1);
    v.fixture.destroy();
  });

  it('keeps one tab stop and moves it with the arrow keys', async () => {
    const v = await render();
    expect(v.bars().filter(row => row.tabIndex === 0)).toHaveLength(1);
    v.bars()[0].focus(); const event = v.key(v.bars()[0], 'ArrowRight'); await v.settle();
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(v.bars()[1]);
    expect(v.bars().map(row => row.tabIndex)).toEqual([-1, 0, -1]);
    v.key(v.bars()[1], 'ArrowLeft'); expect(document.activeElement).toBe(v.bars()[0]);
    v.fixture.destroy();
  });

  it('extends a draft with Shift+Arrow, announces it, applies it with Enter and cancels it with Escape', async () => {
    const v = await render(); const bars = v.bars();
    bars[0].focus();
    v.key(bars[0], 'ArrowRight', { shiftKey: true }); v.key(bars[1], 'ArrowRight', { shiftKey: true }); await v.settle();
    expect(document.activeElement).toBe(bars[2]);
    expect(bars.every(row => row.getAttribute('aria-pressed') === 'true')).toBe(true);
    expect(v.root.querySelector('[role=status]')!.textContent).toContain('timeline.range_draft{"from":"01/01/2019","to":"31/12/2021"}');
    expect(v.filters.dateFrom()).toBe('');
    const escape = v.key(bars[2], 'Escape'); await v.settle();
    expect(escape.defaultPrevented).toBe(true);
    expect(bars.every(row => row.getAttribute('aria-pressed') === 'false')).toBe(true);
    expect(v.root.querySelector('[role=status]')!.textContent?.trim()).toBe('');
    expect(v.key(bars[2], 'Escape').defaultPrevented).toBe(false);
    v.key(bars[2], 'ArrowLeft', { shiftKey: true }); await v.settle();
    const enter = v.key(bars[1], 'Enter'); await v.settle();
    expect(enter.defaultPrevented).toBe(true);
    expect(v.filters.dateFrom()).toBe('2020-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('treats Enter without a draft as a plain click', async () => {
    const v = await render(); v.bars()[1].focus();
    expect(v.key(v.bars()[1], 'Enter').defaultPrevented).toBe(false);
    v.bars()[1].click(); await v.settle();
    expect(v.navigate).toHaveBeenCalledWith(['/timeline', '2020']);
    v.fixture.destroy();
  });

  it('switches the unit with a button-toggle group (year level only) and the log scale with a pressed button', async () => {
    const v = await render();
    expect(v.root.querySelector('mat-button-toggle-group')).toBeNull(); expect(v.root.querySelector('select')).toBeNull();
    v.fixture.componentRef.setInput('year', '2019'); v.api.get.mockReturnValue(of({ months: [{ month: '2019-01', count: 10 }, { month: '2019-02', count: 2 }] })); await v.settle();
    const toggles = [...v.root.querySelectorAll('mat-button-toggle')];
    expect(toggles.map(row => row.textContent?.trim())).toEqual(['timeline.density_months', 'timeline.density_weeks']);
    const before = v.bars()[1].querySelector<HTMLElement>('[aria-hidden=true] > span')!.style.height;
    const log = v.button('timeline.log_scale'); expect(log.getAttribute('aria-pressed')).toBe('false');
    log.click(); await v.settle();
    expect(log.getAttribute('aria-pressed')).toBe('true');
    expect(v.bars()[1].querySelector<HTMLElement>('[aria-hidden=true] > span')!.style.height).not.toBe(before);
    expect(v.bars()[1].getAttribute('aria-label')).toContain('"count":2');
    expect(v.api.get).toHaveBeenCalledTimes(2);
    v.fixture.destroy();
  });

  it('shows zero-count days and the leap day in the selected month', async () => {
    const v = await render({ year: '2024', month: '2' });
    v.api.get.mockReturnValueOnce(of({ dates: [{ date: '2024-02-28', count: 3 }] })); v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline/dates', expect.objectContaining({ year: 2024, month: 2 }), expect.anything());
    expect(v.bars()).toHaveLength(29); expect(v.bars()[28].getAttribute('aria-label')).toContain('"period":"2024-02-29","count":0');
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
    const v = await render(); const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending);
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(pending.observed).toBe(true); await v.router.navigateByUrl('/elsewhere'); await v.settle();
    expect(pending.observed).toBe(false); pending.next(years); expect(v.bars()).toHaveLength(0);
    v.auth.status.set({ user_id: 'bob' }); v.auth.token = 'b'; await v.settle(); expect(v.bars()).toHaveLength(0); v.fixture.destroy();
  });

  it('reports a failed count read and retries without presenting an empty library', async () => {
    const v = await render(); v.api.get.mockReturnValueOnce(throwError(() => new Error('offline')));
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(v.root.querySelector('[role=alert]')).not.toBeNull(); expect(v.root.textContent).not.toContain('timeline.empty');
    v.button('timeline.retry').click(); await v.settle(); expect(v.bars()).toHaveLength(3); v.fixture.destroy();
  });

  it('refuses a drill or an apply after token rotation', async () => {
    const v = await render(); const bars = v.bars();
    bars[0].focus(); v.key(bars[0], 'ArrowRight', { shiftKey: true }); await v.settle();
    v.auth.token = 'b'; v.key(bars[1], 'Enter'); bars[0].click();
    expect(v.filters.dateFrom()).toBe(''); expect(v.filters.dateTo()).toBe(''); expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('clears stale Calendar reads on account changes and provides real error/retry state', async () => {
    const v = await render(); v.fixture.destroy(); const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending);
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
    calendar.destroy();
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
