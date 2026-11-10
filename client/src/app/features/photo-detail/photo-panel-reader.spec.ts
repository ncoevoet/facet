import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Event as RouterEvent, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoProvenanceComponent } from './photo-provenance.component';

describe('PhotoPanelReader on a same-path edit of the open photo', () => {
  let http: HttpTestingController;
  let status: ReturnType<typeof signal<object | null>>;
  let session: ReturnType<typeof signal<string | null>>;

  beforeEach(() => {
    status = signal<object | null>({ user_id: 'alice' });
    session = signal<string | null>('alice|token');
    TestBed.configureTestingModule({
      imports: [PhotoProvenanceComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { status, session, token: 'token' } },
        { provide: Router, useValue: { events: new Subject<RouterEvent>() } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });

  it('keeps an expanded panel open and its data shown when a rating edit replaces the photo object', () => {
    const fixture = TestBed.createComponent(PhotoProvenanceComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg', star_rating: 1 }));
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const trigger = root.querySelector<HTMLElement>('mat-expansion-panel-header')!;
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ review_scope: 'personal', review: [], manual_tags: [{ tag: 'kept tag', source: 'xmp' }], manual_tags_truncated: false, capture_date_override: false, gps_override: false });
    fixture.detectChanges();
    expect(root.textContent).toContain('kept tag');
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg', star_rating: 4 })); fixture.detectChanges();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ review_scope: 'personal', review: [], manual_tags: [{ tag: 'fresh tag', source: 'local' }], manual_tags_truncated: false, capture_date_override: false, gps_override: false });
    fixture.detectChanges();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(root.textContent).toContain('fresh tag');
  });

  const PROVENANCE = { review_scope: 'personal', review: [], manual_tags: [{ tag: 'kept tag', source: 'xmp' }], manual_tags_truncated: false, capture_date_override: false, gps_override: false };

  function openPanel(): { root: HTMLElement; trigger: HTMLElement; detect: () => void } {
    const fixture = TestBed.createComponent(PhotoProvenanceComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg' }));
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const trigger = root.querySelector<HTMLElement>('mat-expansion-panel-header')!;
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush(PROVENANCE);
    fixture.detectChanges();
    return { root, trigger, detect: () => fixture.detectChanges() };
  }

  it('stays open through a same-session revalidation that replaces and briefly nulls the status', () => {
    const { root, trigger, detect } = openPanel();
    status.set(null); detect();
    status.set({ user_id: 'alice' }); detect();
    http.expectNone(() => true);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(root.textContent).toContain('kept tag');
  });

  it('collapses and drops its data when the session changes', () => {
    const { root, trigger, detect } = openPanel();
    status.set({ user_id: 'bob' }); session.set('bob|token'); detect();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(root.textContent).not.toContain('kept tag');
  });

  it('still collapses and drops its data when another photo is opened', () => {
    const fixture = TestBed.createComponent(PhotoProvenanceComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/a.jpg' }));
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const trigger = root.querySelector<HTMLElement>('mat-expansion-panel-header')!;
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/provenance?path=/a.jpg').flush({ review_scope: 'personal', review: [], manual_tags: [{ tag: 'old tag', source: 'xmp' }], manual_tags_truncated: false, capture_date_override: false, gps_override: false });
    fixture.detectChanges();
    fixture.componentRef.setInput('photo', makePhoto({ path: '/b.jpg' })); fixture.detectChanges();
    http.expectNone(() => true);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(root.textContent).not.toContain('old tag');
  });
});
