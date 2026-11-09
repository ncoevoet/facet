import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of, Subject, throwError } from 'rxjs';
import { TimelineFeedComponent } from './timeline-feed.component';
import { TimelineFiltersService } from './timeline-filters.service';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFeedCache, type TimelinePage } from './timeline-feed-cache.service';
import type { Photo } from '../../shared/models/photo.model';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';

@Component({ template: '' }) class OtherPage {}
const first = { groups: [{ date: '2026-11-01', count: 12, photos: [
  { path: '/first.jpg', filename: 'first.jpg', preview_revision: 'v1' },
] }], next_cursor: '2026-11-01', has_more: true } as TimelinePage;

describe('Timeline photo feed', () => {
  async function setup() {
    const api = { get: vi.fn().mockReturnValue(of(first)) };
    const auth = { status: signal({ user_id: 'alice', authenticated: true }), token: 'a' };
    const visibility = signal({ hide_bursts: '1', hide_duplicates: '0' });
    const photos = signal<Photo[]>([]);
    const timelineMembershipRevision = signal(0);
    const loading = signal(false);
    TestBed.configureTestingModule({ imports: [TimelineFeedComponent], providers: [
      provideRouter([{ path: 'timeline', component: OtherPage }, { path: 'timeline/:year/:month', component: OtherPage }, { path: 'photo', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: GalleryStore, useValue: { viewFilterParams: visibility, photos, timelineMembershipRevision, loading } },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    const router = TestBed.inject(Router); await router.navigateByUrl('/timeline');
    function create() {
      const fixture = TestBed.createComponent(TimelineFeedComponent);
      const wrapper = document.createElement('app-timeline'); wrapper.appendChild(fixture.nativeElement); document.body.appendChild(wrapper);
      const settle = async () => { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); };
      const dispose = () => { fixture.destroy(); wrapper.remove(); };
      return { fixture, root: fixture.nativeElement as HTMLElement, wrapper, settle, dispose };
    }
    const view = create(); await view.settle();
    return { ...view, create, api, auth, visibility, photos, timelineMembershipRevision, loading, router, filters: TestBed.inject(TimelineFiltersService) };
  }

  it('renders actual dated photos, preview totals and exact visible-day links without writes', async () => {
    const v = await setup();
    expect(v.root.querySelector('h2')?.textContent).toBe('01/11/2026');
    expect(v.root.textContent).toContain('"shown":1,"total":12');
    expect(v.root.querySelector('img')?.getAttribute('src')).toContain('preview=v1');
    const day = v.root.querySelector<HTMLAnchorElement>('section header a')!;
    expect(day.href).toContain('sort_direction=DESC'); expect(day.href).toContain('date_from=2026-11-01'); expect(day.href).toContain('hide_bursts=true');
    expect(v.root.querySelector<HTMLAnchorElement>('section .grid a')?.href).toContain('/photo?path=%2Ffirst.jpg');
    expect(v.api.get).toHaveBeenCalledExactlyOnceWith('/timeline', expect.objectContaining({ photos_per_group: 8, limit: 8, sort_by: 'date_taken', hide_bursts: '1' }), expect.anything());
    expect(v.api.get.mock.calls[0][2].get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
    v.dispose();
  });

  it('retains loaded dates on a failed next page and retries the same cursor', async () => {
    const v = await setup(); v.api.get.mockReturnValueOnce(throwError(() => new Error('offline')));
    v.root.querySelector<HTMLButtonElement>('button[mat-stroked-button]')!.click(); await v.settle();
    expect(v.root.querySelector('h2')?.textContent).toBe('01/11/2026'); expect(v.root.querySelector('[role=alert]')).not.toBeNull();
    v.api.get.mockReturnValueOnce(of({ groups: [{ date: '2026-10-31', count: 0, photos: [] }], next_cursor: null, has_more: false }));
    const retry = [...v.root.querySelectorAll('button')].find(button => button.textContent?.includes('timeline.retry'))!;
    retry.click(); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline', expect.objectContaining({ cursor: '2026-11-01' }), expect.anything());
    expect(v.root.querySelectorAll('h2')).toHaveLength(2); expect(v.root.querySelector('[role=alert]')).toBeNull(); v.dispose();
  });

  it('keeps pagination focus through a failed request and retry without stealing it', async () => {
    const v = await setup(); const pending = new Subject<TimelinePage>();
    v.api.get.mockReturnValueOnce(pending);
    const button = v.root.querySelector<HTMLButtonElement>('[data-timeline-load-more]')!;
    button.focus(); button.click(); await v.settle();
    expect(document.activeElement).toBe(button);
    expect(button.getAttribute('aria-disabled')).toBe('true');
    pending.error(new Error('offline')); await v.settle();
    expect(document.activeElement).toBe(button);
    expect(button.textContent).toContain('timeline.retry');
    const next = new Subject<TimelinePage>(); v.api.get.mockReturnValueOnce(next);
    button.click(); await v.settle();
    const other = v.root.querySelector<HTMLInputElement>('input[type=month]')!; other.focus();
    next.next({ groups: [], next_cursor: null, has_more: false }); await v.settle();
    expect(document.activeElement).toBe(other); v.dispose();
  });

  it('moves focus to the final loaded photo when the pagination control disappears', async () => {
    const v = await setup(); const next = new Subject<TimelinePage>(); v.api.get.mockReturnValueOnce(next);
    const button = v.root.querySelector<HTMLButtonElement>('[data-timeline-load-more]')!;
    button.focus(); button.click(); await v.settle();
    next.next({ groups: [
      { date: '2026-10-31', count: 1, photos: [{ path: '/first-new.jpg', filename: 'first-new.jpg' }] },
      { date: '2026-10-30', count: 1, photos: [{ path: '/last.jpg', filename: 'last.jpg' }] },
    ], next_cursor: null, has_more: false } as TimelinePage);
    await v.settle(); await v.settle();
    expect((document.activeElement as HTMLElement).getAttribute('aria-label')).toBe('first-new.jpg');
    v.dispose();
  });

  it('intersects month routes and capture range, and restarts when visibility changes', async () => {
    const v = await setup(); v.fixture.componentRef.setInput('year', '2026'); v.fixture.componentRef.setInput('month', '2');
    v.filters.dateFrom.set('2026-02-12'); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline', expect.objectContaining({ date_from: '2026-02-12', date_to: '2026-02-28' }), expect.anything());
    v.visibility.set({ hide_bursts: '0', hide_duplicates: '0' }); await v.settle();
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline', expect.objectContaining({ hide_bursts: '0', cursor: '' }), expect.anything()); v.dispose();
  });

  it('cancels stale reads when leaving and ignores a prior account completion', async () => {
    const v = await setup(); const pending = new Subject<TimelinePage>();
    v.api.get.mockReturnValueOnce(pending); v.filters.sortDirection.set('newer'); await v.settle();
    expect(pending.observed).toBe(true);
    await v.router.navigateByUrl('/photo?path=%2Ffirst.jpg'); await v.settle(); expect(pending.observed).toBe(false);
    pending.next(first); expect(v.root.querySelectorAll('h2')).toHaveLength(0);
    v.auth.status.set({ user_id: 'bob', authenticated: true }); v.auth.token = 'b'; await v.settle();
    expect(v.root.querySelector('img')).toBeNull(); v.dispose();
  });

  it('keeps an in-flight read when the scope is re-emitted unchanged, but restarts on a real change', async () => {
    const v = await setup(); const pending = new Subject<TimelinePage>();
    v.api.get.mockReturnValueOnce(pending); v.filters.sortDirection.set('newer'); await v.settle();
    expect(pending.observed).toBe(true); const calls = v.api.get.mock.calls.length;
    v.visibility.set({ hide_bursts: '1', hide_duplicates: '0' }); await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(calls); expect(pending.observed).toBe(true);
    pending.next(first); await v.settle();
    expect(v.root.querySelector('h2')?.textContent).toBe('01/11/2026');
    v.visibility.set({ hide_bursts: '0', hide_duplicates: '0' }); await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(calls + 1); v.dispose();
  });

  it('restores the same owner feed and scroll after photo Back without another photo read', async () => {
    const v = await setup(); v.wrapper.scrollTop = 240; v.wrapper.dispatchEvent(new Event('scroll'));
    await v.router.navigateByUrl('/photo?path=%2Ffirst.jpg'); v.dispose();
    await v.router.navigateByUrl('/timeline'); const returned = v.create(); await returned.settle();
    expect(returned.root.querySelector('h2')?.textContent).toBe('01/11/2026'); expect(returned.wrapper.scrollTop).toBe(240);
    expect(v.api.get).toHaveBeenCalledTimes(1); returned.dispose();
  });

  it('reads once after a Gallery reload settles, keeping the current feed during the temporary clear', async () => {
    const v = await setup();
    v.photos.set([first.groups[0].photos[0]]); await v.settle(); v.api.get.mockClear();
    v.loading.set(true);
    v.photos.set([]); await v.settle();
    expect(v.api.get).not.toHaveBeenCalled();
    expect(v.root.querySelector('h2')?.textContent).toBe('01/11/2026');
    v.photos.set([first.groups[0].photos[0]]); await v.settle();
    expect(v.api.get).not.toHaveBeenCalled();
    v.timelineMembershipRevision.update(value => value + 1); v.loading.set(false); await v.settle();
    expect(v.api.get).toHaveBeenCalledTimes(1);
    expect(v.root.querySelector('h2')?.textContent).toBe('01/11/2026');
    v.dispose();
  });

  it('invalidates a pending Timeline read immediately for an explicit mutation during Gallery loading', async () => {
    const v = await setup(); const response = new Subject<TimelinePage>();
    v.api.get.mockReturnValueOnce(response);
    v.filters.sortDirection.set('newer'); await v.settle();
    expect(response.observed).toBe(true);
    v.api.get.mockClear(); v.loading.set(true); await v.settle();
    expect(response.observed).toBe(true); expect(v.api.get).not.toHaveBeenCalled();
    v.timelineMembershipRevision.update(value => value + 1); await v.settle();
    expect(response.observed).toBe(false); expect(v.api.get).toHaveBeenCalledTimes(1);
    response.next({ groups: [{ date: '1999-01-01', count: 0, photos: [] }], next_cursor: null, has_more: false });
    expect(v.root.textContent).not.toContain('01/01/1999');
    v.dispose();
  });

  it('preserves the feed and scroll when a photo receives a review mark', async () => {
    const v = await setup();
    v.photos.set([first.groups[0].photos[0]]); await v.settle(); v.api.get.mockClear();
    v.wrapper.scrollTop = 240; v.wrapper.dispatchEvent(new Event('scroll'));
    await v.router.navigateByUrl('/photo?path=%2Ffirst.jpg'); v.dispose();
    v.photos.update(rows => rows.map(photo => ({ ...photo, star_rating: 4, is_kept: true })));
    await v.router.navigateByUrl('/timeline'); const returned = v.create(); await returned.settle();
    expect(returned.wrapper.scrollTop).toBe(240); expect(returned.root.querySelector('img')).not.toBeNull();
    expect(v.api.get).not.toHaveBeenCalled(); returned.dispose();
  });

  it('captures the displayed preview sequence on the actual thumbnail click before navigation parks the feed', async () => {
    const v = await setup();
    const photos = [...first.groups[0].photos, { path: '/second.jpg', filename: 'second.jpg' }];
    v.api.get.mockReturnValueOnce(of({ ...first, groups: [{ ...first.groups[0], photos }] }));
    v.visibility.set({ hide_bursts: '0', hide_duplicates: '0' }); await v.settle();
    const navigate = vi.spyOn(v.router, 'navigate');
    v.root.querySelector<HTMLAnchorElement>('section .grid a')!.click(); await v.settle();
    expect(v.router.url).toBe('/photo?path=%2Ffirst.jpg');
    expect(TestBed.inject(TimelineFeedCache).adjacent('/first.jpg', 1)).toBe('/second.jpg');
    expect(navigate).toHaveBeenCalledWith(['/photo'], expect.objectContaining({ state: expect.objectContaining({ photoOrigin: 'timeline' }) })); v.dispose();
  });

  it.each([{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }])(
    'leaves modified thumbnail clicks to the browser: %j', async modifiers => {
      const v = await setup(); const navigate = vi.spyOn(v.router, 'navigate');
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, ...modifiers });
      v.root.querySelector<HTMLAnchorElement>('section .grid a')!.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false); expect(navigate).not.toHaveBeenCalled();
      expect(TestBed.inject(TimelineFeedCache).adjacent('/first.jpg', 1)).toBeNull(); v.dispose();
    });

  it('drives direction and month navigation from the visible controls', async () => {
    const v = await setup();
    v.root.querySelector<HTMLButtonElement>('div > button')!.click(); await v.settle();
    expect(v.filters.sortDirection()).toBe('newer');
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline', expect.objectContaining({ direction: 'newer' }), expect.anything());
    const month = v.root.querySelector<HTMLInputElement>('input[type=month]')!;
    month.value = '2026-02'; month.dispatchEvent(new Event('change', { bubbles: true })); await v.settle();
    expect(v.router.url).toBe('/timeline/2026/2'); v.dispose();
  });

  it.each(['older', 'newer'] as const)('continues after the 128-day cap in the %s direction', async direction => {
    const v = await setup(); v.filters.sortDirection.set(direction);
    const groups = Array.from({ length: 128 }, (_, index) => ({
      date: new Date(Date.UTC(2026, 10, 1 - index)).toISOString().slice(0, 10), count: 0, photos: [],
    }));
    const cursor = groups[127].date;
    v.api.get.mockReturnValueOnce(of({ groups, has_more: true, next_cursor: cursor }));
    v.visibility.set({ hide_bursts: '0', hide_duplicates: '0' }); await v.settle();
    expect(v.root.querySelectorAll('h2')).toHaveLength(128);
    v.wrapper.scrollTop = 240;
    const button = [...v.root.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.includes('timeline.continue_dates'))!;
    expect(button).toBeTruthy();
    v.api.get.mockReturnValueOnce(of({ groups: [], has_more: false, next_cursor: null }));
    button.click(); await v.settle();
    const expected = direction === 'older' ? '2026-06-26' : '2026-06-28';
    expect(direction === 'older' ? v.filters.dateTo() : v.filters.dateFrom()).toBe(expected);
    expect(v.api.get).toHaveBeenLastCalledWith('/timeline', expect.objectContaining(direction === 'older' ? { date_to: expected, cursor: '' } : { date_from: expected, cursor: '' }), expect.anything());
    expect(v.wrapper.scrollTop).toBe(0); v.dispose();
  });

  it.each(['removed', 'capture-date changed'])('re-reads instead of returning a stale tile after a photo was %s', async change => {
    const v = await setup();
    v.photos.set([first.groups[0].photos[0]]); await v.settle(); v.api.get.mockClear();
    await v.router.navigateByUrl('/photo?path=%2Ffirst.jpg'); v.dispose();
    if (change === 'removed') v.photos.set([]);
    else v.photos.update(rows => rows.map(photo => ({ ...photo, date_taken: '2026-10-31' })));
    v.api.get.mockReturnValueOnce(of({ groups: [], next_cursor: null, has_more: false }));
    await v.router.navigateByUrl('/timeline'); const returned = v.create(); await returned.settle();
    expect(v.api.get).toHaveBeenCalledTimes(1); expect(returned.root.querySelector('img')).toBeNull(); returned.dispose();
  });
});
