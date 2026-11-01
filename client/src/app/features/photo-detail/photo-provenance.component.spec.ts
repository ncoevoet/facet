import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationCancel, NavigationStart, Router } from '@angular/router';
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
  let auth: { status: ReturnType<typeof signal<object | null>>; token: string };
  let events: Subject<NavigationStart | NavigationCancel>;
  let http: HttpTestingController;

  beforeEach(() => {
    auth = { status: signal<object | null>({ user_id: 'alice' }), token: 'original-token' };
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

  function render() {
    const fixture = TestBed.createComponent(PhotoProvenanceComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg' }));
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    return { fixture, root, trigger: root.querySelector('summary')!, panel: root.querySelector('details')! };
  }

  it('requests only on expansion, renders explicit zero and imported source, and closes help-first with focus return', () => {
    const { fixture, root, trigger, panel } = render();
    document.body.appendChild(root);
    http.expectNone(() => true);
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/provenance?path=/a.jpg');
    expect(request.request.method).toBe('GET'); request.flush(response); fixture.detectChanges();
    expect(root.textContent).toContain('rating.stars 0');
    expect(root.textContent).toContain('metadata_sources.personal');
    expect(root.textContent).toContain('from xmp');
    expect(root.textContent).not.toContain('metadata_sources.help ');
    const help = root.querySelector<HTMLDetailsElement>('[data-context-help]')!;
    help.open = true; help.dispatchEvent(new Event('toggle')); fixture.detectChanges();
    expect(help.querySelector('[data-context-help-close]')).not.toBeNull();
    help.querySelector('summary')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(help.open).toBe(false); expect(panel.open).toBe(true);
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    trigger.dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true); expect(panel.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(root.textContent).not.toContain('from xmp');
    expect(root.querySelector('details')!.open).toBe(false);
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
    expect(root.querySelector('details')!.open).toBe(false);
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
    expect(request.cancelled).toBe(true); expect(root.querySelector('details')!.open).toBe(false);
  });

  it('does not display a response delivered after credential rotation', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/provenance?path=/a.jpg');
    auth.token = 'replacement-token';
    request.flush(response); fixture.detectChanges();
    expect(root.textContent).not.toContain('from xmp');
    expect(root.querySelector('details')!.open).toBe(false);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(response); fixture.detectChanges();
    expect(root.textContent).toContain('from xmp');
  });
});
