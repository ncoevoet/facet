import { TestBed } from '@angular/core/testing';
import { ComparisonSessionService } from './comparison-session.service';
import { By } from '@angular/platform-browser';
import { vi } from 'vitest';
import { ComparisonWorkspaceComponent } from './comparison-workspace.component';
import { FIT_ZOOM, SyncedZoomComponent } from './synced-zoom.component';
import { MAX_COMPARE_PANES } from './comparison-slots.util';
import { Photo } from '../../shared/models/photo.model';
import { I18nService } from '../../core/services/i18n.service';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { signal } from '@angular/core';
import { NavigationCancel, NavigationCancellationCode, NavigationStart, provideRouter, Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { sharedInspectionPeople } from './comparison-inspection.util';

const photo = (path: string): Photo => ({ path, filename: path.slice(1) } as Photo);

function build(paths: string[]) {
  const data = { photos: paths.map(photo), returnUrl: '/?search=captured' };
  const session = { snapshot: () => data, clear: vi.fn() };
  const authStatus = signal({ user_id: 'alice' });
  const api = { get: vi.fn(), post: vi.fn() };
  api.get.mockReturnValue(of({ faces: [] }));
  api.post.mockReturnValue(of({ key_subjects_by_path: {} }));
  TestBed.configureTestingModule({
    imports: [ComparisonWorkspaceComponent],
    providers: [
      provideRouter([]),
      { provide: ApiService, useValue: api },
      { provide: AuthService, useValue: { status: authStatus, identity: () => authStatus().user_id, isEdition: () => false, token: null } },
      { provide: ComparisonSessionService, useValue: session },
      { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
    ],
  });
  const router = TestBed.inject(Router);
  vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
  const fixture = TestBed.createComponent(ComparisonWorkspaceComponent);
  fixture.detectChanges();
  return { fixture, router, api, authStatus, data, session };
}

describe('ComparisonWorkspaceComponent', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders one synced pane per selected photo', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom');
    expect(panes.length).toBe(2);
  });

  it('counts visible comparison panes after switching a four-photo set to two-up', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const i18n = TestBed.inject(I18nService);
    const translate = vi.spyOn(i18n, 't');
    fixture.nativeElement.querySelector('[data-two-up]').click(); fixture.detectChanges();
    expect(translate).toHaveBeenCalledWith('gallery.compare.title', { count: 2 });
    expect(fixture.nativeElement.querySelectorAll('[data-candidate-thumbnail]')).toHaveLength(4);
  });

  it('renders a 2x2 grid for four photos', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length).toBe(4);
  });

  it('drops photos beyond the pane cap rather than shrinking them all', () => {
    const paths = Array.from({ length: MAX_COMPARE_PANES + 3 }, (_, i) => `/p${i}.jpg`);
    const { fixture } = build(paths);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length)
      .toBe(MAX_COMPARE_PANES);
  });

  it('gives each pane its own stored thumbnail as placeholder, keyed by its frame', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const urls = new ThumbnailUrlPipe();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent))
      .map(de => de.componentInstance as SyncedZoomComponent);
    expect(panes.map(p => p.placeholderSrc())).toEqual([urls.transform('/a.jpg', 640), urls.transform('/b.jpg', 640)]);
    expect(panes.map(p => p.frameKey())).toEqual(['/a.jpg', '/b.jpg']);
  });

  it('a zoom from one pane drives every other pane', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    const next = { scale: 3, tx: 12, ty: -8 };
    panes[0].componentInstance.zoomChange.emit(next);
    fixture.detectChanges();
    expect(panes[0].componentInstance.zoom()).toEqual(next);
    expect(panes[1].componentInstance.zoom()).toEqual(next);
  });

  it('starts fitted and offers the reset only once zoomed', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const resetSelector = 'button[aria-label="gallery.compare.reset_zoom"]';
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).toBeNull();

    const pane = fixture.debugElement.query(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    pane.componentInstance.zoomChange.emit({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).not.toBeNull();

    fixture.debugElement.nativeElement.querySelector(resetSelector).click();
    fixture.detectChanges();
    expect(pane.componentInstance.zoom()).toEqual(FIT_ZOOM);
  });

  it('returns to the exact captured collection URL without a dialog', () => {
    const { fixture, router } = build(['/a.jpg', '/b.jpg']);
    fixture.debugElement.nativeElement.querySelector('button[aria-label="ui.buttons.back"]').click();
    expect(router.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/?search=captured');
  });

  it('recovers from cancelled navigation without adopting a different account', () => {
    const { fixture, router, authStatus } = build(['/a.jpg', '/b.jpg']);
    const events = router.events as Subject<unknown>;
    events.next(new NavigationStart(2, '/albums'));
    events.next(new NavigationCancel(2, '/albums', 'cancelled', NavigationCancellationCode.GuardRejected));
    fixture.detectChanges();
    fixture.nativeElement.querySelector('[data-link-inspection]').click(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-link-inspection]').getAttribute('aria-pressed')).toBe('false');
    events.next(new NavigationStart(3, '/albums'));
    authStatus.set({ user_id: 'bob' });
    events.next(new NavigationCancel(3, '/albums', 'cancelled', NavigationCancellationCode.GuardRejected));
    fixture.detectChanges();
    expect(router.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/', { replaceUrl: true });
  });
  it('does not let a cancelled inspection overwrite a fresh retry after route cancellation', async () => {
    const { fixture, router, api } = build(['/a.jpg', '/b.jpg']);
    const old = new Subject<unknown>();
    api.get.mockReturnValue(old); api.post.mockReturnValue(old);
    const component = fixture.componentInstance as unknown as { loadInspection(): Promise<void>; inspectionState(): string };
    const obsolete = component.loadInspection();
    const events = router.events as Subject<unknown>;
    events.next(new NavigationStart(2, '/albums'));
    events.next(new NavigationCancel(2, '/albums', 'cancelled', NavigationCancellationCode.GuardRejected));
    const response = new Subject<unknown>();
    api.get.mockReturnValue(response); api.post.mockReturnValue(response);
    const retry = component.loadInspection();
    await obsolete;
    expect(old.observed).toBe(false);
    expect(component.inspectionState()).toBe('loading');
    response.next({ faces: [], key_subjects_by_path: {} });
    await retry;
    expect(component.inspectionState()).toBe('ready');
  });

  it('Escape closes inspection first and then returns to the collection', () => {
    const { fixture, router } = build(['/a.jpg', '/b.jpg']);
    fixture.nativeElement.querySelector('[data-inspection-toggle]').click(); fixture.detectChanges();
    fixture.nativeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#comparison-inspection')).toBeNull();
    expect(router.navigateByUrl).not.toHaveBeenCalled();
    fixture.nativeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(router.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/?search=captured');
  });

  it('loads bounded stored inspection data only on explicit Inspect and offers retry after failure', async () => {
    const { fixture, api } = build(['/a.jpg', '/b.jpg']);
    expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
    api.post.mockReturnValue(throwError(() => new Error('offline')));
    const component = fixture.componentInstance as unknown as { loadInspection(): Promise<void>; inspectionState(): string };
    await component.loadInspection(); fixture.detectChanges();
    expect(component.inspectionState()).toBe('partial');
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/photos/key_subjects', { paths: ['/a.jpg', '/b.jpg'] });
    api.post.mockReturnValue(of({ key_subjects_by_path: {} }));
    await component.loadInspection(); fixture.detectChanges();
    expect(component.inspectionState()).toBe('ready');
    fixture.nativeElement.querySelector('[data-inspection-toggle]').click(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#comparison-inspection')).not.toBeNull();
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it('cancels reads and discards late inspection answers as soon as closing starts', async () => {
    const { fixture, api, router } = build(['/a.jpg', '/b.jpg']);
    const response = new Subject<unknown>();
    api.get.mockReturnValue(response); api.post.mockReturnValue(response);
    const component = fixture.componentInstance as unknown as { loadInspection(): Promise<void>; inspectionState(): string };
    const pending = component.loadInspection();
    expect(response.observed).toBe(true);
    (router.events as Subject<unknown>).next(new NavigationStart(2, '/albums'));
    await pending;
    expect(response.observed).toBe(false);
    expect(component.inspectionState()).toBe('loading');
  });

  it('closes a read-only comparison when its account context changes', () => {
    const { fixture, authStatus, router } = build(['/a.jpg', '/b.jpg']);
    authStatus.set({ user_id: 'bob' }); fixture.detectChanges();
    expect(router.navigateByUrl).toHaveBeenCalledOnce();
  });

  it('frames one unambiguous saved person in each visible pane, independently and atomically', async () => {
    const { fixture, api } = build(['/a.jpg', '/b.jpg']);
    api.get.mockImplementation((_url, params) => of({ faces: [{ id: params.path === '/a.jpg' ? 1 : 2, face_index: 0, person_id: 7, person_name: 'Ada', box: [0.5, 0.25, 0.75, 0.5] }] }));
    const component = fixture.componentInstance as unknown as { loadInspection(): Promise<void> };
    await component.loadInspection();
    fixture.nativeElement.querySelector('[data-inspection-toggle]').click(); fixture.detectChanges();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(de => de.componentInstance as SyncedZoomComponent);
    const first = vi.spyOn(panes[0], 'zoomForRegion').mockReturnValue({ scale: 3, tx: 20, ty: -10 });
    const second = vi.spyOn(panes[1], 'zoomForRegion').mockReturnValue(null);
    const select = fixture.nativeElement.querySelector('[data-shared-person]') as HTMLSelectElement;
    select.value = '7'; select.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(panes.map(p => p.zoom())).toEqual([FIT_ZOOM, FIT_ZOOM]);
    second.mockReturnValue({ scale: 2, tx: -30, ty: 10 });
    select.value = '7'; select.dispatchEvent(new Event('change')); fixture.detectChanges();
    expect(first).toHaveBeenCalledWith([0.5, 0.25, 0.75, 0.5], undefined);
    expect(panes.map(p => p.zoom().scale)).toEqual([3, 2]);
    expect(fixture.nativeElement.querySelector('[data-link-inspection]').getAttribute('aria-pressed')).toBe('false');
    expect(fixture.nativeElement.textContent).toContain('gallery.compare.inspection.review_link');
  });

  it('keeps manual alignment at linked zoom bounds and reserves explicit reset for Fit', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    fixture.nativeElement.querySelector('[data-link-inspection]').click(); fixture.detectChanges();
    panes[0].componentInstance.zoomChange.emit({ scale: 1.1, tx: 20, ty: 10 }); fixture.detectChanges();
    fixture.nativeElement.querySelector('[data-link-inspection]').click(); fixture.detectChanges();
    const host = panes[0].nativeElement as HTMLElement;
    host.dispatchEvent(new KeyboardEvent('keydown', { key: '-', bubbles: true })); fixture.detectChanges();
    host.dispatchEvent(new WheelEvent('wheel', { deltaY: 1000, bubbles: true })); fixture.detectChanges();
    expect(panes[0].componentInstance.zoom()).toEqual({ scale: 1.1, tx: 20, ty: 10 });
    expect(panes[1].componentInstance.zoom()).toEqual(FIT_ZOOM);
    expect([...fixture.nativeElement.querySelectorAll('[data-zoom-out]')].every((button: any) => button.disabled)).toBe(true);
    host.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); fixture.detectChanges();
    expect(panes.map(p => p.componentInstance.zoom())).toEqual([FIT_ZOOM, FIT_ZOOM]);
  });

  it('requires saved identity and one valid occurrence, never merely equal face indexes', () => {
    const face = { id: 1, face_index: 0, person_id: 0, person_name: 'Ada', box: [0.1, 0.2, 0.4, 0.6] };
    const rows = new Map([['/a', [face]], ['/b', [{ ...face, id: 2 }]]]);
    expect(sharedInspectionPeople(['/a', '/b'], rows).map(p => p.id)).toEqual([0]);
    rows.set('/b', [{ ...face, person_id: 8 }]);
    expect(sharedInspectionPeople(['/a', '/b'], rows)).toEqual([]);
    rows.set('/b', [face, { ...face, id: 2 }]);
    expect(sharedInspectionPeople(['/a', '/b'], rows)).toEqual([]);
    rows.set('/b', [{ ...face, box: [0.1, 0.2, 2, 0.6] }]);
    expect(sharedInspectionPeople(['/a', '/b'], rows)).toEqual([]);
  });

  it('retains unusable face occurrences when deciding whether API-loaded correspondence is ambiguous', async () => {
    const { fixture, api } = build(['/a.jpg', '/b.jpg']);
    const face = { id: 1, face_index: 0, person_id: 7, person_name: 'Ada', box: [0.1, 0.2, 0.4, 0.6] };
    api.get.mockImplementation((_url, params) => of({ faces: params.path === '/a.jpg' ? [face, { ...face, id: 2, face_index: 1, box: null }] : [face] }));
    const component = fixture.componentInstance as unknown as { loadInspection(): Promise<void>; sharedPeople(): unknown[] };
    await component.loadInspection();
    fixture.nativeElement.querySelector('[data-inspection-toggle]').click(); fixture.detectChanges();
    expect(component.sharedPeople()).toEqual([]);
    expect(fixture.nativeElement.querySelector('[data-shared-person]').disabled).toBe(true);
    expect(fixture.nativeElement.querySelector('[data-frame-face]').querySelectorAll('option')).toHaveLength(2);
  });

  it('preserves manual alignment when relinking and applies relative gestures until an explicit reset', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    const toggle = fixture.nativeElement.querySelector('[data-link-inspection]');
    expect(toggle).not.toBeNull();
    toggle.click();
    fixture.detectChanges();
    const next = { scale: 3, tx: 17, ty: -4 };
    panes()[1].componentInstance.zoomChange.emit(next);
    fixture.detectChanges();
    expect(panes()[0].componentInstance.zoom()).toEqual(FIT_ZOOM);
    expect(panes()[1].componentInstance.zoom()).toEqual(next);
    toggle.click();
    fixture.detectChanges();
    expect(panes().map(p => p.componentInstance.zoom())).toEqual([FIT_ZOOM, next]);
    panes()[1].componentInstance.zoomChange.emit({ scale: 6, tx: 29, ty: -12 });
    fixture.detectChanges();
    expect(panes().map(p => p.componentInstance.zoom())).toEqual([
      { scale: 2, tx: -5, ty: -4 }, { scale: 6, tx: 29, ty: -12 },
    ]);
    fixture.nativeElement.querySelector('button[aria-label="gallery.compare.reset_zoom"]').click();
    fixture.detectChanges();
    expect(panes().map(p => p.componentInstance.zoom())).toEqual([FIT_ZOOM, FIT_ZOOM]);
  });

  it('bounds linked magnification together and retains aligned candidates while cycling two-up', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const panes = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    const toggle = root.querySelector<HTMLButtonElement>('[data-link-inspection]')!;
    toggle.click(); fixture.detectChanges();
    panes()[0].componentInstance.zoomChange.emit({ scale: 2, tx: 10, ty: -4 });
    panes()[1].componentInstance.zoomChange.emit({ scale: 4, tx: -20, ty: 8 });
    fixture.detectChanges();
    toggle.click(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click(); fixture.detectChanges();
    const oldCandidate = panes()[1].componentInstance as SyncedZoomComponent;
    root.querySelector<HTMLButtonElement>('[data-candidate-next]')!.click(); fixture.detectChanges();
    oldCandidate.zoomChange.emit({ scale: 8, tx: 900, ty: 900 });
    panes()[0].componentInstance.zoomChange.emit({ scale: 8, tx: 15, ty: -2 });
    fixture.detectChanges();
    // The hidden candidate reaches 8x first, so the group stops at a 2x ratio.
    expect(panes().map(p => p.componentInstance.zoom())).toEqual([
      { scale: 4, tx: 15, ty: -2 }, { scale: 2, tx: -5, ty: 6 },
    ]);
    root.querySelector<HTMLButtonElement>('[data-candidate-previous]')!.click(); fixture.detectChanges();
    expect(panes()[1].componentInstance.zoom()).toEqual({ scale: 8, tx: -45, ty: 22 });
    expect(panes().every(p => Number.isFinite(p.componentInstance.zoom().scale))).toBe(true);
  });

  it('keeps manually aligned points together when linked panes have different scales and offsets', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    const toggle = fixture.nativeElement.querySelector('[data-link-inspection]');
    toggle.click(); fixture.detectChanges();
    panes()[0].componentInstance.zoomChange.emit({ scale: 2, tx: -100, ty: -40 });
    panes()[1].componentInstance.zoomChange.emit({ scale: 4, tx: -200, ty: -80 });
    fixture.detectChanges();
    toggle.click(); fixture.detectChanges();
    panes()[0].componentInstance.zoomChange.emit({ scale: 4, tx: -100, ty: -40 });
    fixture.detectChanges();
    const frames = panes().map(p => p.componentInstance.zoom());
    // The same measured feature was at the center in both manually framed panes.
    // It may move with the gesture, but must keep its relative alignment.
    const positions = frames.map(frame => ({ x: 50 * frame.scale + frame.tx, y: 20 * frame.scale + frame.ty }));
    expect(positions).toEqual([{ x: 100, y: 40 }, { x: 100, y: 40 }]);
  });

  it('promotes a reference without changing pane membership or writing a review decision', () => {
    const paths = ['/a.jpg', '/b.jpg', '/c.jpg'];
    const { fixture, router } = build(paths);
    const reference = () => fixture.nativeElement.querySelector('[data-reference="true"]');
    expect(reference()).not.toBeNull();
    expect(reference().textContent).toContain('a.jpg');
    fixture.nativeElement.querySelectorAll('[data-promote-reference]')[0].click();
    fixture.detectChanges();
    expect(reference().textContent).toContain('b.jpg');
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(paths);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('reports actual displayed source loading and failure independently of preview preload', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    panes[1].componentInstance.zoomChange.emit({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();
    panes[0].componentInstance.sharpFailed.emit('/a-preview');
    panes[1].componentInstance.sharpLoaded.emit('/b-preview');
    panes[0].componentInstance.renditionChange.emit({ kind: 'thumbnail', phase: 'ready', width: 640, height: 480 });
    panes[1].componentInstance.renditionChange.emit({ kind: 'source', phase: 'loading' });
    fixture.detectChanges();
    const statuses = () => Array.from(fixture.nativeElement.querySelectorAll('[data-preview-status]') as NodeListOf<HTMLElement>).map(p => p.textContent);
    expect(statuses()[0]).toContain('gallery.compare.rendition.fallback');
    expect(statuses()[1]).toContain('gallery.compare.rendition.source');
    expect(statuses()[1]).toContain('gallery.compare.rendition.loading');
    panes[1].componentInstance.renditionChange.emit({ kind: 'source', phase: 'failed' });
    fixture.detectChanges();
    const renderer = panes[1].componentInstance as SyncedZoomComponent;
    const retry = vi.spyOn(renderer, 'retry');
    fixture.nativeElement.querySelectorAll('[data-retry-pane]')[1].click();
    expect(retry).toHaveBeenCalledOnce();
    expect(statuses()[1]).toContain('gallery.compare.rendition.failed');
    fixture.detectChanges();
    renderer.renditionChange.emit({ kind: 'source', phase: 'ready', width: 4000, height: 3000 });
    fixture.detectChanges();
    expect(statuses()[1]).toContain('4000 × 3000');
    expect(renderer.fullResSrc()).not.toContain('fallback');
  });

  it('offers explicit zoom and Fit for linked and independently aligned panes', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance as SyncedZoomComponent);
    root.querySelector<HTMLButtonElement>('[data-zoom-in]')!.click(); fixture.detectChanges();
    expect(panes.map(p => p.zoom().scale)).toEqual([1.5, 1.5]);
    root.querySelector<HTMLButtonElement>('[data-link-inspection]')!.click(); fixture.detectChanges();
    root.querySelectorAll<HTMLButtonElement>('[data-zoom-in]')[1].click(); fixture.detectChanges();
    expect(panes.map(p => p.zoom().scale)).toEqual([1.5, 2.25]);
    root.querySelectorAll<HTMLButtonElement>('[data-fit-pane]')[1].click(); fixture.detectChanges();
    expect(panes.map(p => p.zoom().scale)).toEqual([1.5, 1]);
    root.querySelector<HTMLButtonElement>('[data-link-inspection]')!.click(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-fit-pane]')!.click(); fixture.detectChanges();
    expect(panes.map(p => p.zoom())).toEqual([FIT_ZOOM, FIT_ZOOM]);
  });

  it('cycles only candidates in two-up mode and swaps the old reference back into the candidate slot on promotion', () => {
    const { fixture, router } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    expect(root.querySelector('[data-two-up]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
    expect(root.querySelector<HTMLButtonElement>('[data-candidate-previous]')!.disabled).toBe(true);
    root.querySelector<HTMLButtonElement>('[data-candidate-next]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    root.querySelector<HTMLButtonElement>('[data-promote-reference]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/c.jpg', '/a.jpg']);
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('moves candidates backward and stops at both boundaries without changing the reference', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    const previous = root.querySelector<HTMLButtonElement>('[data-candidate-previous]')!;
    const next = root.querySelector<HTMLButtonElement>('[data-candidate-next]')!;
    next.click(); fixture.detectChanges();
    next.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/d.jpg']);
    expect(next.disabled).toBe(true);
    next.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/d.jpg']);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
    expect(previous.disabled).toBe(true);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
  });
  it('assigns any thumbnail to reference or candidate explicitly without review writes', () => {
    const { fixture, api } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const thumbs = () => root.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]');
    const frames = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    root.querySelector<HTMLButtonElement>('[data-compare-target="reference"]')!.click(); fixture.detectChanges();
    thumbs()[2].click(); fixture.detectChanges();
    expect(frames()).toEqual(['/c.jpg', '/b.jpg']);
    root.querySelector<HTMLButtonElement>('[data-compare-target="candidate"]')!.click(); fixture.detectChanges();
    thumbs()[3].click(); fixture.detectChanges();
    expect(frames()).toEqual(['/c.jpg', '/d.jpg']);
    root.querySelector<HTMLButtonElement>('[data-compare-target="reference"]')!.click(); fixture.detectChanges();
    thumbs()[3].click(); fixture.detectChanges();
    expect(frames()).toEqual(['/d.jpg', '/c.jpg']);
    root.querySelector<HTMLButtonElement>('[data-compare-target="candidate"]')!.click(); fixture.detectChanges();
    thumbs()[3].click(); fixture.detectChanges();
    expect(frames()).toEqual(['/c.jpg', '/d.jpg']);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows a thumbnail queue and opens a chosen candidate without promoting it', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const queue = root.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]');
    expect(queue).toHaveLength(4);
    queue[3].click(); fixture.detectChanges();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    expect(panes.map(p => p.componentInstance.frameKey())).toEqual(['/a.jpg', '/d.jpg']);
    expect(root.querySelector('[data-reference="true"]')!.textContent).toContain('a.jpg');
    expect(root.querySelector('[data-candidate-thumbnail][aria-pressed="true"]')!.getAttribute('data-path')).toBe('/d.jpg');
  });

  it('removes the reference from this view only, chooses a surviving reference and can restore the original set', () => {
    const { fixture, router } = build(['/a.jpg', '/b.jpg', '/c.jpg']);
    const data = TestBed.inject(ComparisonSessionService).snapshot();
    data.photos[0].is_rejected = false;
    data.photos[1].is_kept = true;
    const before = JSON.stringify(data.photos);
    const root = fixture.nativeElement as HTMLElement;
    root.querySelector<HTMLButtonElement>('[data-remove-pane]')!.click(); fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(['/b.jpg', '/c.jpg']);
    expect(root.querySelector('[data-reference="true"]')!.textContent).toContain('b.jpg');
    expect(root.querySelectorAll('[data-candidate-thumbnail]')).toHaveLength(2);
    root.querySelector<HTMLButtonElement>('[data-restore-comparison]')!.click(); fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
    expect(JSON.stringify(data.photos)).toBe(before);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('advances after removing a candidate and keeps one remaining photo inspectable', () => {
    const { fixture, router } = build(['/a.jpg', '/b.jpg', '/c.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    root.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]')[1].click(); fixture.detectChanges();
    root.querySelectorAll<HTMLButtonElement>('[data-remove-pane]')[1].click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    root.querySelectorAll<HTMLButtonElement>('[data-remove-pane]')[1].click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg']);
    expect(root.querySelector<HTMLButtonElement>('[data-remove-pane]')!.disabled).toBe(true);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

});
