import { OverlayContainer } from '@angular/cdk/overlay';
import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Event as RouterEvent, NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import type { PhotoProvenance } from '../../core/api/types';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoProvenanceComponent } from './photo-provenance.component';

describe('PhotoProvenanceComponent', () => {
  const response: PhotoProvenance = {
    review_scope: 'personal',
    review: [{ field: 'star_rating', value: 0, source: 'local', changed_at: null, source_at: null }],
    manual_tags: [{ tag: 'from xmp', source: 'xmp' }], manual_tags_truncated: false,
    capture_date_override: true, gps_override: false,
  };
  let auth: { status: ReturnType<typeof signal<object | null>>; session: () => string | null; token: string };
  let events: Subject<RouterEvent>;
  let http: HttpTestingController;

  beforeEach(() => {
    const status = signal<object | null>({ user_id: 'alice' });
    auth = { status, session: computed(() => (status() as { user_id?: string } | null)?.user_id ?? null), token: 'original-token' };
    events = new Subject();
    TestBed.configureTestingModule({
      imports: [PhotoProvenanceComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: auth },
        { provide: Router, useValue: { events } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });

  /** The cells of the review-table row headed by `label`. */
  function rowText(root: HTMLElement, label: string): string[] {
    const row = [...root.querySelectorAll('[data-provenance-review] tbody tr')].find(tr => tr.querySelector('th')!.textContent!.trim() === label)!;
    return [...row.children].map(cell => cell.textContent!.trim());
  }

  function render() {
    const fixture = TestBed.createComponent(PhotoProvenanceComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg' }));
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const trigger = root.querySelector<HTMLElement>('mat-expansion-panel-header')!;
    return { fixture, root, trigger, panel: { get open() { return trigger.getAttribute('aria-expanded') === 'true'; } } };
  }
  const isOpen = (root: HTMLElement) => root.querySelector('mat-expansion-panel-header')!.getAttribute('aria-expanded') === 'true';

  it('renders boolean decisions, source labels and metadata override notices', () => {
    const { fixture, root, trigger } = render(); trigger.click();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ ...response, manual_tags: [], manual_tags_truncated: true,
      capture_date_override: false, gps_override: true, review: [
        { field: 'is_kept', value: true, source: 'local', changed_at: null, source_at: null },
        { field: 'is_rejected', value: false, source: 'unrecorded', changed_at: null, source_at: null },
        { field: 'is_favorite', value: true, source: 'xmp', changed_at: null, source_at: null },
      ] }); fixture.detectChanges();
    expect(rowText(root, 'review.kept')).toEqual(['review.kept', 'organization_history.yes', 'metadata_sources.local']);
    expect(rowText(root, 'review.rejected')).toEqual(['review.rejected', 'organization_history.no', 'metadata_sources.unrecorded']);
    expect(root.textContent).toContain('metadata_sources.gps_override');
    expect(root.textContent).not.toContain('metadata_sources.date_override');
    expect(root.textContent).toContain('metadata_sources.no_tags');
    expect(root.textContent).toContain('metadata_sources.tag_limit');
  });

  it.each([
    new NavigationEnd(2, '/photo', '/photo'),
    new NavigationError(2, '/photo', new Error('route failure')),
    new NavigationSkipped(2, '/photo', 'same route'),
    new NavigationCancel(2, '/photo', 'guard refused'),
  ])('permits a new read after navigation settles: $constructor.name', event => {
    const { fixture, trigger } = render();
    events.next(new NavigationStart(2, '/photo'));
    trigger.click(); http.expectNone(() => true);
    events.next(event);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response);
  });

  it('stays blocked across redirect, superseded and obsolete navigation completions', () => {
    const { fixture, trigger } = render();
    events.next(new NavigationStart(2, '/photo'));
    events.next(new NavigationCancel(2, '/photo', 'redirect', NavigationCancellationCode.Redirect));
    trigger.click(); http.expectNone(() => true);
    events.next(new NavigationStart(3, '/photo'));
    events.next(new NavigationCancel(2, '/photo', 'superseded', NavigationCancellationCode.SupersededByNewNavigation));
    events.next(new NavigationEnd(2, '/photo', '/photo'));
    trigger.click(); http.expectNone(() => true);
    events.next(new NavigationEnd(3, '/photo', '/photo'));
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response);
  });

  it('requests only on expansion, renders explicit zero and imported source, and closes help-first with focus return', () => {
    const { fixture, root, trigger, panel } = render();
    document.body.appendChild(root);
    http.expectNone(() => true);
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/provenance?path=/a.jpg');
    expect(request.request.method).toBe('GET'); request.flush(response); fixture.detectChanges();
    expect(rowText(root, 'rating.stars')).toEqual(['rating.stars', '0']);
    expect(root.textContent).toContain('metadata_sources.personal');
    expect(root.textContent).toContain('from xmp');
    expect(root.textContent).not.toContain('metadata_sources.help ');
    const helpTrigger = root.querySelector<HTMLButtonElement>('app-context-help button')!;
    helpTrigger.click(); fixture.detectChanges();
    const help = TestBed.inject(OverlayContainer).getContainerElement();
    expect(help.querySelector('header button')).not.toBeNull();
    help.querySelector('header button')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(help.querySelector('[role="dialog"]')).toBeNull(); expect(panel.open).toBe(true);
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    trigger.dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true); expect(panel.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(root.textContent).not.toContain('from xmp');
    expect(isOpen(root)).toBe(false);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response); fixture.detectChanges();
    expect(root.textContent).toContain('from xmp');
    fixture.destroy(); root.remove();
  });

  it('cancels old-photo reads, clears old data, and retries a failed fresh read without writes', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    const old = http.expectOne('/api/photo/provenance?path=/a.jpg');
    fixture.componentRef.setInput('photo', makePhoto({ path: '/b.jpg' })); fixture.detectChanges();
    expect(old.cancelled).toBe(true);
    expect(isOpen(root)).toBe(false);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/b.jpg').flush({}, { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges(); expect(root.querySelector('[role="alert"]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('button')!.click();
    http.expectOne('/api/photo/provenance?path=/b.jpg').flush(response); fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBeNull(); expect(root.textContent).toContain('from xmp');
  });

  it('clears on account invalidation and navigation, blocks pending navigation, permits a fresh cancelled-navigation request', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response); fixture.detectChanges();
    auth.status.set(null); fixture.detectChanges();
    expect(root.textContent).not.toContain('from xmp');
    trigger.click(); http.expectNone(() => true);
    auth.status.set({ user_id: 'bob' }); fixture.detectChanges();
    events.next(new NavigationStart(1, '/persons'));
    trigger.click(); http.expectNone(() => true);
    events.next(new NavigationCancel(1, '/persons', 'guard refused'));
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/provenance?path=/a.jpg');
    events.next(new NavigationStart(2, '/')); fixture.detectChanges();
    expect(request.cancelled).toBe(true); expect(isOpen(root)).toBe(false);
  });

  it('does not display a response delivered after credential rotation', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/provenance?path=/a.jpg');
    auth.token = 'replacement-token';
    request.flush(response); fixture.detectChanges();
    expect(root.textContent).not.toContain('from xmp');
    expect(isOpen(root)).toBe(false);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response); fixture.detectChanges();
    expect(root.textContent).toContain('from xmp');
  });

  it('shows an unknown catalog rating as unavailable while keeping an explicit zero numeric', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ ...response, review_scope: 'catalog',
      review: [{ field: 'star_rating', value: null, source: 'unrecorded', changed_at: null, source_at: null }] });
    fixture.detectChanges();
    expect(root.textContent).toContain('photo_detail.assessment.unavailable');
    expect(rowText(root, 'rating.stars')).toEqual(['rating.stars', 'photo_detail.assessment.unavailable']);
    trigger.click(); fixture.detectChanges(); trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response); fixture.detectChanges();
    expect(rowText(root, 'rating.stars')).toEqual(['rating.stars', '0']);
    expect(root.textContent).not.toContain('photo_detail.assessment.unavailable');
  });

  it('collapses a source every review field shares into one line, and every tag source likewise', () => {
    const { fixture, root, trigger } = render(); trigger.click();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ ...response, review: [
      { field: 'star_rating', value: 3, source: 'unrecorded', changed_at: null, source_at: null },
      { field: 'is_favorite', value: false, source: 'unrecorded', changed_at: null, source_at: null },
    ], manual_tags: [{ tag: 'a', source: 'xmp' }, { tag: 'b', source: 'xmp' }] }); fixture.detectChanges();
    const table = root.querySelector('[data-provenance-review]')!;
    expect([...table.querySelectorAll('thead th')].map(th => th.textContent!.trim())).toEqual(['metadata_sources.field', 'metadata_sources.value']);
    expect(rowText(root, 'rating.favorite')).toEqual(['rating.favorite', 'organization_history.no']);
    expect(root.querySelector('[data-provenance-review-source]')!.textContent).toContain('metadata_sources.all_fields');
    expect(root.querySelector('[data-provenance-tag-source]')!.textContent).toContain('metadata_sources.all_tags');
    expect(root.textContent!.match(/metadata_sources\.unrecorded/g)).toBeNull();
  });

  it('keeps a Source column when review fields come from different sources, with the help icon beside the scope heading', () => {
    const { fixture, root, trigger } = render(); trigger.click();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ ...response, review: [
      { field: 'star_rating', value: 3, source: 'xmp', changed_at: null, source_at: null },
      { field: 'is_favorite', value: true, source: 'local', changed_at: null, source_at: null },
    ] }); fixture.detectChanges();
    expect([...root.querySelectorAll('[data-provenance-review] thead th')].map(th => th.textContent!.trim()))
      .toEqual(['metadata_sources.field', 'metadata_sources.value', 'metadata_sources.source']);
    expect(root.querySelector('[data-provenance-review-source]')).toBeNull();
    const help = root.querySelector<HTMLButtonElement>('[data-provenance-scope] app-context-help button')!;
    expect(help.getAttribute('aria-label')).toBe('metadata_sources.help_title');
    expect(help.textContent!.trim()).toBe('help_outline');
  });
});
