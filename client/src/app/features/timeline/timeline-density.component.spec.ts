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
import { densityBuckets, densityIndexAt, densityLabelStep, densityRange, timelineWindow, type DensityResponse } from './timeline-density.util';
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

  const matchMedia = window.matchMedia;
  const resizeObserver = globalThis.ResizeObserver;

  /** `wide` is the lg+ layout; below lg the strip is a touch scrubber. */
  async function render(inputs: Record<string, unknown> = {}, wide = true) {
    // A plain function, as in test-setup: a vi.fn would lose its implementation to another spec's restoreAllMocks.
    window.matchMedia = (query: string) => ({ ...matchMedia(query), matches: wide });
    const api = { get: vi.fn().mockReturnValue(of(years)) };
    const auth = { status: signal<{ user_id: string } | null>({ user_id: 'alice' }), session: signal<string | null>('alice|a'), token: 'a' };
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
    /** Lay the strip out as 0..width px wide and 0..92 px tall, as a phone would. */
    const strip = (width: number) => {
      const element = root.querySelector<HTMLElement>('[role=group]')!;
      element.getBoundingClientRect = () => ({ left: 0, right: width, top: 0, bottom: 92, width, height: 92, x: 0, y: 0, toJSON: () => ({}) });
      return element;
    };
    const readout = () => root.querySelector<HTMLElement>('[data-density-readout]')!;
    return { fixture, root, api, auth, photos, timelineMembershipRevision, loading, router, navigate, totals, settle, bars, button, key, pointer, under, strip, readout, filters: TestBed.inject(TimelineFiltersService) };
  }

  afterEach(() => {
    delete (document as unknown as { elementFromPoint?: unknown }).elementFromPoint;
    window.matchMedia = matchMedia; globalThis.ResizeObserver = resizeObserver; vi.useRealTimers();
  });

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
    expect(bar.className).toContain('max-lg:min-w-0');
    const tip = v.fixture.debugElement.queryAll(By.directive(MatTooltip)).find(debug => debug.nativeElement === bar)!.injector.get(MatTooltip);
    expect(tip.message).toContain('"count":"12,345"');
    expect(tip.touchGestures).toBe('auto');
    expect(bar.getAttribute('aria-label')).toContain('"count":12345');
    expect(v.root.querySelector('[role=group]')!.getAttribute('aria-label')).toBe('timeline.density_years');
    expect(v.root.textContent).not.toContain('timeline.density_years');
    v.fixture.destroy();
  });

  it('stacks the controls above the chart below lg so the chart keeps the full row', async () => {
    const v = await render();
    const wrapper = v.root.querySelector<HTMLElement>('[data-timeline-density-row]')!;
    expect(wrapper.className).toContain('flex-col');
    expect(wrapper.className).toContain('lg:flex-row');
    expect(wrapper.className).toContain('lg:items-start');
    const controls = v.root.querySelector<HTMLElement>('[data-timeline-density-controls]')!;
    expect(controls.className).toContain('flex-wrap');
    expect(controls.className).toContain('justify-end');
    expect(wrapper.firstElementChild).toBe(controls);
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

  it('from lg up does not drag with touch pointers: a tap drills', async () => {
    const v = await render(); const bars = v.bars();
    v.pointer('pointerdown', bars[0], { pointerType: 'touch' }); v.under(bars[2]); v.pointer('pointermove', bars[2], { pointerType: 'touch' });
    v.pointer('pointerup', bars[2], { pointerType: 'touch' }); await v.settle();
    expect(v.filters.dateFrom()).toBe(''); expect(bars.every(row => row.getAttribute('aria-pressed') === 'false')).toBe(true);
    bars[0].click(); await v.settle();
    expect(v.navigate).toHaveBeenCalledWith(['/timeline', '2019']);
    v.fixture.destroy();
  });

  /** The browser's order for a mouse press: focus lands between pointerdown and click. */
  function shiftClick(v: { pointer: (type: string, target: Element, init?: Record<string, unknown>) => boolean }, bar: HTMLElement) {
    v.pointer('pointerdown', bar, { shiftKey: true }); bar.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, shiftKey: true }));
    bar.focus(); v.pointer('pointerup', bar, { shiftKey: true }); bar.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, shiftKey: true }));
    bar.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey: true, detail: 1 }));
  }

  it('Shift+click on a keyboard-focused bar applies anchor..clicked, ignoring the pointer focus, without drilling', async () => {
    const v = await render(); const bars = v.bars();
    bars[0].focus(); await v.settle();
    shiftClick(v, bars[2]); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('applies the range in either order when the clicked bar precedes the anchor', async () => {
    const v = await render(); const bars = v.bars();
    bars[2].focus(); await v.settle();
    shiftClick(v, bars[1]); await v.settle();
    expect(v.filters.dateFrom()).toBe('2020-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    v.fixture.destroy();
  });

  it('without an anchor, the first Shift+click only sets it and the second applies the range', async () => {
    const v = await render(); const bars = v.bars();
    shiftClick(v, bars[0]); await v.settle();
    expect(v.navigate).not.toHaveBeenCalled(); expect(v.filters.dateFrom()).toBe('');
    expect(bars[0].getAttribute('aria-pressed')).toBe('true'); expect(bars[1].getAttribute('aria-pressed')).toBe('false');
    shiftClick(v, bars[2]); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
    expect(v.navigate).not.toHaveBeenCalled();
    v.fixture.destroy();
  });

  it('Escape clears a pending Shift+click anchor, so the next Shift+click starts over', async () => {
    const v = await render(); const bars = v.bars();
    shiftClick(v, bars[0]); await v.settle();
    v.key(bars[0], 'Escape'); await v.settle();
    expect(bars[0].getAttribute('aria-pressed')).toBe('false');
    shiftClick(v, bars[2]); await v.settle();
    expect(v.filters.dateFrom()).toBe(''); expect(bars[2].getAttribute('aria-pressed')).toBe('true');
    v.fixture.destroy();
  });

  it('Shift+click extends a Shift+Arrow draft from its anchor', async () => {
    const v = await render(); const bars = v.bars();
    bars[0].focus(); v.key(bars[0], 'ArrowRight', { shiftKey: true }); await v.settle();
    shiftClick(v, bars[2]); await v.settle();
    expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
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
    expect(toggles.map(row => row.querySelector('[data-unit-long]')?.textContent?.trim())).toEqual(['timeline.density_months', 'timeline.density_weeks']);
    // Below sm a short label keeps the toggle and the log button on one row; the full one stays its name.
    expect(toggles.map(row => row.querySelector('[data-unit-short]')?.textContent?.trim())).toEqual(['timeline.density_months_short', 'timeline.density_weeks_short']);
    expect(toggles.every(row => row.querySelector('[data-unit-long]')!.classList.contains('max-sm:hidden'))).toBe(true);
    expect(toggles.every(row => row.querySelector('[data-unit-short]')!.classList.contains('sm:hidden'))).toBe(true);
    expect(toggles.map(row => row.querySelector('button')?.getAttribute('aria-label'))).toEqual(['timeline.density_months', 'timeline.density_weeks']);
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
    v.auth.status.set({ user_id: 'bob' }); v.auth.token = 'b'; v.auth.session.set('bob|b'); await v.settle(); expect(v.bars()).toHaveLength(0); v.fixture.destroy();
  });

  it('keeps the strip, its draft and an in-flight read through a same-session revalidation and its transient null', async () => {
    const v = await render(); const bars = v.bars(); const calls = v.api.get.mock.calls.length;
    bars[0].focus(); v.key(bars[0], 'ArrowRight', { shiftKey: true }); await v.settle();
    v.auth.status.set({ user_id: 'alice' }); await v.settle();
    v.auth.status.set(null); await v.settle();
    v.auth.status.set({ user_id: 'alice' }); await v.settle();
    expect(v.bars()).toHaveLength(3); expect(v.api.get).toHaveBeenCalledTimes(calls);
    expect(v.bars().slice(0, 2).every(row => row.getAttribute('aria-pressed') === 'true')).toBe(true);
    v.key(v.bars()[1], 'Enter'); await v.settle(); expect(v.filters.dateFrom()).toBe('2019-01-01');
    const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending);
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    v.auth.status.set(null); await v.settle(); v.auth.status.set({ user_id: 'alice' }); await v.settle();
    expect(pending.observed).toBe(true); pending.next(years); await v.settle(); expect(v.bars()).toHaveLength(3);
    v.auth.status.set(null); v.auth.session.set(null); await v.settle(); expect(v.bars()).toHaveLength(0); v.fixture.destroy();
  });

  it('keeps a loaded Calendar and its in-flight read through a same-session revalidation and its transient null', async () => {
    const v = await render(); v.fixture.destroy();
    const calendar = TestBed.createComponent(TimelineYearsComponent); calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges();
    const settle = async () => { calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges(); };
    const shown = () => calendar.nativeElement.querySelectorAll('[data-timeline-result]').length; const loaded = shown(); const calls = v.api.get.mock.calls.length;
    expect(loaded).toBeGreaterThan(0);
    v.auth.status.set({ user_id: 'alice' }); await settle(); v.auth.status.set(null); await settle();
    v.auth.status.set({ user_id: 'alice' }); await settle();
    expect(shown()).toBe(loaded); expect(v.api.get).toHaveBeenCalledTimes(calls);
    const pending = new Subject<DensityResponse>(); v.api.get.mockReturnValueOnce(pending); v.filters.dateFrom.set('2019-01-01'); await settle();
    v.auth.status.set(null); await settle(); v.auth.status.set({ user_id: 'alice' }); await settle();
    expect(pending.observed).toBe(true); expect(v.api.get).toHaveBeenCalledTimes(calls + 1);
    v.auth.status.set(null); v.auth.session.set(null); await settle(); expect(pending.observed).toBe(false); calendar.destroy();
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
    v.auth.status.set({ user_id: 'bob' }); v.auth.token = 'b'; v.auth.session.set('bob|b'); calendar.detectChanges(); await calendar.whenStable(); calendar.detectChanges();
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

  describe('below lg, as a touch scrubber', () => {
    type View = Awaited<ReturnType<typeof render>>;
    /** A finger: touch pointers stay captured by the bar they went down on, so only the position moves. */
    const touch = (v: View, type: string, target: Element, clientX: number, init: Record<string, unknown> = {}) =>
      v.pointer(type, target, { pointerType: 'touch', pointerId: 7, clientX, clientY: 40, ...init });

    it('finds the bucket under a pointer position, clamped to the ends of the strip', () => {
      expect(densityIndexAt(10, 0, 300, 3)).toBe(0);
      expect(densityIndexAt(150, 0, 300, 3)).toBe(1);
      expect(densityIndexAt(299, 0, 300, 3)).toBe(2);
      expect(densityIndexAt(-40, 0, 300, 3)).toBe(0);
      expect(densityIndexAt(900, 0, 300, 3)).toBe(2);
      expect(densityIndexAt(120, 100, 31, 31)).toBe(20);
      expect(densityIndexAt(50, 0, 0, 3)).toBe(0);
    });

    it('labels every bar whose label fits, else every n-th bar', () => {
      const years = Array.from({ length: 24 }, (_, index) => String(2002 + index));
      expect(densityLabelStep(years, 1000)).toBe(1);
      expect(densityLabelStep(years, 328)).toBe(3);
      expect(densityLabelStep(Array.from({ length: 12 }, (_, index) => String(index + 1).padStart(2, '0')), 328)).toBe(1);
      expect(densityLabelStep(Array.from({ length: 31 }, (_, index) => String(index + 1)), 328)).toBe(3);
      expect(densityLabelStep(years, 0)).toBe(1);
    });

    it('shares the width with no scroll, labels every n-th bar, and leaves touch to the strip rather than tooltips', async () => {
      let resized: ResizeObserverCallback | null = null;
      globalThis.ResizeObserver = class {
        constructor(callback: ResizeObserverCallback) { resized = callback; }
        observe(): void {} unobserve(): void {} disconnect(): void {}
      } as unknown as typeof ResizeObserver;
      const v = await render({}, false);
      const strip = v.root.querySelector<HTMLElement>('[role=group]')!;
      for (const cls of ['max-lg:overflow-x-clip', 'max-lg:touch-pan-y']) expect(strip.classList).toContain(cls);
      expect(v.bars()[0].className).toContain('max-lg:min-w-0');
      const tips = v.fixture.debugElement.queryAll(By.directive(MatTooltip))
        .filter(debug => v.bars().includes(debug.nativeElement)).map(debug => debug.injector.get(MatTooltip));
      expect(tips.map(tip => tip.touchGestures)).toEqual(['off', 'off', 'off']);
      // Three year labels need 108 px; in 60 px only every second bar keeps one, and never one that would run off the end.
      resized!([{ contentRect: { width: 60 } } as ResizeObserverEntry], {} as ResizeObserver); await v.settle();
      const labels = v.bars().map(bar => bar.lastElementChild!);
      expect(labels.map(label => label.classList.contains('max-lg:invisible'))).toEqual([false, true, true]);
      expect(labels[0].classList).toContain('max-lg:text-left');
      // A label runs over the next bars; positioned, it paints above their highlight instead of under it.
      expect(labels[0].classList).toContain('max-lg:relative');
      v.fixture.destroy();
    });

    it('reads the bucket under a finger in a live readout above the strip, and drills the one it lifts on', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      expect(v.readout().getAttribute('role')).toBe('status');
      expect(v.readout().className).toContain('sr-only');
      // detectChanges, not settle: whenStable would wait out the pending hold and draft a range.
      touch(v, 'pointerdown', bars[0], 10); v.fixture.detectChanges();
      expect(v.readout().className).not.toContain('sr-only');
      expect(v.readout().textContent).toContain('timeline.period_count{"period":"2019","count":"1"}');
      expect(v.readout().textContent).toContain('timeline.scrub_hint');
      touch(v, 'pointermove', bars[0], 150); v.fixture.detectChanges();
      expect(v.readout().textContent).toContain('"period":"2020","count":"100"');
      expect(bars[1].className).toContain('surface-container-highest');
      expect(v.navigate).not.toHaveBeenCalled();
      touch(v, 'pointerup', bars[0], 150); bars[0].click(); await v.settle();
      expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2020']);
      expect(v.readout().className).toContain('sr-only');
      expect(v.filters.dateFrom()).toBe('');
      v.fixture.destroy();
    });

    it('drills a tapped bar once, though the browser follows the tap with a click', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      touch(v, 'pointerdown', bars[2], 250); touch(v, 'pointerup', bars[2], 250); bars[2].click(); await v.settle();
      expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2021']);
      v.fixture.destroy();
    });

    it('does not let a slide that ends without a click swallow the next keyboard Enter', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      touch(v, 'pointerdown', bars[0], 10); touch(v, 'pointermove', bars[0], 250); touch(v, 'pointerup', bars[0], 250); await v.settle();
      expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2021']);
      v.navigate.mockClear(); bars[1].focus(); v.key(bars[1], 'Enter'); bars[1].click(); await v.settle();
      expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2020']);
      v.fixture.destroy();
    });

    it('reads without drilling when the finger lifts off the bars or the page takes the gesture for a scroll', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      touch(v, 'pointerdown', bars[1], 150); touch(v, 'pointerup', bars[1], 150, { clientY: 200 }); bars[1].click(); await v.settle();
      touch(v, 'pointerdown', bars[1], 150); touch(v, 'pointercancel', bars[1], 150); await v.settle();
      expect(v.navigate).not.toHaveBeenCalled(); expect(v.readout().className).toContain('sr-only');
      v.fixture.destroy();
    });

    it('picks a range with a long press then a slide, applied to the capture dates on lift', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      touch(v, 'pointerdown', bars[0], 10); touch(v, 'pointermove', bars[0], 15);
      vi.advanceTimersByTime(499); v.fixture.detectChanges();
      expect(bars[0].getAttribute('aria-pressed')).toBe('false');
      vi.advanceTimersByTime(1); v.fixture.detectChanges();
      expect(bars[0].getAttribute('aria-pressed')).toBe('true');
      expect(v.readout().textContent).toContain('01/01/2019 – 31/12/2019');
      expect(v.readout().textContent).toContain('timeline.scrub_range_hint');
      touch(v, 'pointermove', bars[0], 250); v.fixture.detectChanges();
      expect(bars.map(bar => bar.getAttribute('aria-pressed'))).toEqual(['true', 'true', 'true']);
      expect(v.readout().textContent).toContain('01/01/2019 – 31/12/2021');
      expect(v.filters.dateFrom()).toBe('');
      touch(v, 'pointerup', bars[0], 250); bars[0].click(); v.fixture.detectChanges();
      expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
      expect(v.navigate).not.toHaveBeenCalled();
      v.fixture.destroy();
    });

    it('treats a slide before the hold as a read, not a range', async () => {
      const v = await render({}, false); const bars = v.bars(); v.strip(300);
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      touch(v, 'pointerdown', bars[0], 10); touch(v, 'pointermove', bars[0], 250);
      vi.advanceTimersByTime(600); v.fixture.detectChanges();
      expect(bars.every(bar => bar.getAttribute('aria-pressed') === 'false')).toBe(true);
      touch(v, 'pointerup', bars[0], 250); v.fixture.detectChanges();
      expect(v.navigate).toHaveBeenCalledExactlyOnceWith(['/timeline', '2021']); expect(v.filters.dateFrom()).toBe('');
      v.fixture.destroy();
    });

    it('keeps the keyboard: arrows move, Shift+arrows draft an announced range and Enter applies it', async () => {
      const v = await render({}, false); const bars = v.bars();
      expect(v.root.querySelector('[role=group]')!.getAttribute('aria-label')).toBe('timeline.density_years');
      bars[0].focus(); v.key(bars[0], 'ArrowRight'); await v.settle();
      expect(document.activeElement).toBe(bars[1]);
      v.key(bars[1], 'ArrowRight', { shiftKey: true }); await v.settle();
      expect(v.readout().textContent).toContain('timeline.range_draft{"from":"01/01/2020","to":"31/12/2021"}');
      v.key(bars[2], 'Enter'); await v.settle();
      expect(v.filters.dateFrom()).toBe('2020-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
      expect(v.navigate).not.toHaveBeenCalled();
      v.fixture.destroy();
    });

    it('still drags a range with a mouse in a narrow window', async () => {
      const v = await render({}, false); const bars = v.bars();
      v.pointer('pointerdown', bars[0]); v.under(bars[2]); v.pointer('pointermove', bars[2]); v.pointer('pointerup', bars[2]); bars[2].click(); await v.settle();
      expect(v.filters.dateFrom()).toBe('2019-01-01'); expect(v.filters.dateTo()).toBe('2021-12-31');
      expect(v.navigate).not.toHaveBeenCalled();
      v.fixture.destroy();
    });
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
