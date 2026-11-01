import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationCancel, NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import type { RelatedFilesResponse } from '../../core/api/types';
import { makePhoto } from '../../../testing/photo.fixture';
import { PhotoRelatedFilesComponent } from './photo-related-files.component';

describe('PhotoRelatedFilesComponent', () => {
  const response: RelatedFilesResponse = {
    inventory_state: 'checked', indexed_images_only: false, multiple_raw_candidates: false, basename_sidecar_unverified: true,
    files: [
      { name: 'shot.jpg', kind: 'photo', state: 'available', indexed: true, raw_download: false },
      { name: 'shot.CR2', kind: 'raw', state: 'available', indexed: true, raw_download: true },
      { name: 'shot.xmp', kind: 'xmp_basename', state: 'available', indexed: false, raw_download: false },
    ],
  };
  let auth: { status: ReturnType<typeof signal<object | null>>; token: string };
  let events: Subject<NavigationStart | NavigationCancel>;
  let http: HttpTestingController;
  beforeEach(() => {
    auth = { status: signal<object | null>({ user_id: 'alice' }), token: 'one' };
    events = new Subject();
    TestBed.configureTestingModule({
      imports: [PhotoRelatedFilesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: auth }, { provide: Router, useValue: { events } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });
  function render() {
    const fixture = TestBed.createComponent(PhotoRelatedFilesComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/shot.jpg' })); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    return { fixture, root, trigger: root.querySelector('summary')! };
  }

  it('shows an on-demand candidate inventory without file-changing controls and closes on Escape before page navigation', () => {
    const { fixture, root, trigger } = render(); document.body.appendChild(root);
    http.expectNone(() => true);
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/related_files?path=/shot.jpg');
    expect(request.request.method).toBe('GET'); request.flush(response); fixture.detectChanges();
    expect(root.querySelectorAll('li')).toHaveLength(3);
    expect(root.textContent).toContain('shot.CR2'); expect(root.textContent).toContain('related_files.raw_download');
    expect(root.textContent).toContain('related_files.basename_unverified');
    expect(root.querySelector('a')).toBeNull(); expect(root.querySelector('button')).toBeNull();
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    trigger.dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true); expect(root.querySelector('details')!.open).toBe(false);
    expect(document.activeElement).toBe(trigger); expect(root.textContent).not.toContain('shot.CR2');
    fixture.destroy(); root.remove();
  });

  it('cancels obsolete photo reads and offers a fresh retry for an offline result or HTTP failure', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    const old = http.expectOne('/api/photo/related_files?path=/shot.jpg');
    fixture.componentRef.setInput('photo', makePhoto({ path: '/next.jpg' })); fixture.detectChanges();
    expect(old.cancelled).toBe(true);
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/related_files?path=/next.jpg').flush({ ...response, inventory_state: 'unavailable', files: [{ ...response.files[0], state: 'missing' }] });
    fixture.detectChanges(); expect(root.textContent).toContain('related_files.unchecked');
    root.querySelector<HTMLButtonElement>('button')!.click();
    http.expectOne('/api/photo/related_files?path=/next.jpg').flush({}, { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges(); expect(root.querySelector('[role="alert"]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('button')!.click();
    http.expectOne('/api/photo/related_files?path=/next.jpg').flush(response); fixture.detectChanges();
    expect(root.textContent).toContain('shot.CR2'); expect(root.querySelector('[role="alert"]')).toBeNull();
  });

  it('clears owner data, blocks new reads during navigation and discards rotated-credential responses', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/related_files?path=/shot.jpg').flush(response); fixture.detectChanges();
    auth.status.set(null); fixture.detectChanges(); expect(root.textContent).not.toContain('shot.CR2');
    trigger.click(); http.expectNone(() => true);
    auth.status.set({ user_id: 'bob' }); fixture.detectChanges();
    events.next(new NavigationStart(1, '/persons')); trigger.click(); http.expectNone(() => true);
    events.next(new NavigationCancel(1, '/persons', 'cancelled')); trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/related_files?path=/shot.jpg');
    auth.token = 'two'; request.flush(response); fixture.detectChanges();
    expect(root.textContent).not.toContain('shot.CR2'); expect(root.querySelector('details')!.open).toBe(false);
    trigger.click(); fixture.detectChanges(); http.expectOne('/api/photo/related_files?path=/shot.jpg').flush(response);
    fixture.detectChanges(); expect(root.textContent).toContain('shot.CR2');
  });
});
