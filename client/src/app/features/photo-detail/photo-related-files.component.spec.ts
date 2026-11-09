import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { By } from '@angular/platform-browser';
import { PhotoLogicalAssetComponent } from './photo-logical-asset.component';
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
  // The inline RAW/JPEG list has its own spec; here its read is only acknowledged.
  afterEach(() => { try { http.match(request => request.url.startsWith('/api/logical_assets/by-photo')); http.verify(); } finally { TestBed.resetTestingModule(); } });
  function render() {
    const fixture = TestBed.createComponent(PhotoRelatedFilesComponent);
    fixture.componentRef.setInput('photo', makePhoto({ path: '/shot.jpg' })); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    return { fixture, root, trigger: root.querySelector<HTMLElement>('mat-expansion-panel-header')! };
  }
  const isOpen = (root: HTMLElement) => root.querySelector('mat-expansion-panel-header')!.getAttribute('aria-expanded') === 'true';
  /** The RAW/JPEG list renders inline in the open panel and reads its own state. */
  const logical = (path = '/shot.jpg') => http.expectOne(`/api/logical_assets/by-photo?path=${path}`);

  it('shows an on-demand candidate inventory without file-changing controls and closes on Escape before page navigation', () => {
    const { fixture, root, trigger } = render(); document.body.appendChild(root);
    http.expectNone(() => true);
    trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/related_files?path=/shot.jpg');
    expect(request.request.method).toBe('GET'); request.flush(response); fixture.detectChanges();
    expect(root.querySelectorAll('li')).toHaveLength(3);
    expect(root.textContent).toContain('shot.CR2'); expect(root.textContent).toContain('related_files.raw_download');
    expect(root.textContent).toContain('related_files.basename_unverified');
    expect(root.querySelector('a')).toBeNull(); expect([...root.querySelectorAll('button')].filter(button => !button.closest('app-context-help'))).toHaveLength(0);
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    trigger.dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true); expect(isOpen(root)).toBe(false);
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
    root.querySelector<HTMLButtonElement>('[data-related-retry]')!.click();
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
    logical().flush({ asset: null, can_group: false, candidates: [] });
    auth.status.set(null); fixture.detectChanges(); expect(root.textContent).not.toContain('shot.CR2');
    trigger.click(); http.expectNone(() => true);
    auth.status.set({ user_id: 'bob' }); fixture.detectChanges();
    events.next(new NavigationStart(1, '/persons')); trigger.click(); http.expectNone(() => true);
    events.next(new NavigationCancel(1, '/persons', 'cancelled')); trigger.click(); fixture.detectChanges();
    const request = http.expectOne('/api/photo/related_files?path=/shot.jpg');
    auth.token = 'two'; request.flush(response); fixture.detectChanges();
    expect(root.textContent).not.toContain('shot.CR2'); expect(isOpen(root)).toBe(false);
    trigger.click(); fixture.detectChanges(); http.expectOne('/api/photo/related_files?path=/shot.jpg').flush(response);
    fixture.detectChanges(); expect(root.textContent).toContain('shot.CR2');
  });
  it('renders inventory warnings, every candidate label and relays logical changes', () => {
    const { fixture, root, trigger } = render(); trigger.click(); fixture.detectChanges();
    http.expectOne('/api/photo/related_files?path=/shot.jpg').flush({ ...response,
      indexed_images_only: true, multiple_raw_candidates: true,
      files: [
        { name: 'shot.jpeg', kind: 'jpeg', state: 'missing', indexed: true, raw_download: false },
        { name: 'shot.jpg.xmp', kind: 'xmp_full', state: 'unavailable', indexed: false, raw_download: false },
        { name: 'fallback.xmp', kind: 'xmp_fallback', state: 'link', indexed: false, raw_download: false },
      ],
    }); fixture.detectChanges();
    const text = root.textContent!;
    for (const label of ['jpeg', 'missing', 'xmp_full', 'unavailable', 'xmp_fallback', 'link', 'indexed', 'multiple_raw']) {
      expect(text).toContain('related_files.' + label);
    }
    root.querySelector<HTMLButtonElement>('app-context-help button')!.click(); fixture.detectChanges();
    const help = TestBed.inject(OverlayContainer).getContainerElement();
    expect(help.textContent).toContain('related_files.multi_user_scope');
    const emitted = vi.fn(); fixture.componentInstance.logicalApplied.subscribe(emitted);
    const child = fixture.debugElement.query(By.directive(PhotoLogicalAssetComponent)).componentInstance as PhotoLogicalAssetComponent;
    const change = { operation: 'dissolve' as const, assetId: 'a'.repeat(32), primaryPath: null, members: ['/shot.jpg'] };
    child.applied.emit(change);
    expect(emitted).toHaveBeenCalledExactlyOnceWith(change);
  });

  it('lists the RAW/JPEG photo inline once the panel opens, with the help icon beside the file list', () => {
    const { fixture, root, trigger } = render();
    trigger.click(); fixture.detectChanges();
    http.expectNone('/api/logical_assets/by-photo?path=/shot.jpg');
    http.expectOne('/api/photo/related_files?path=/shot.jpg').flush(response); fixture.detectChanges();
    logical().flush({ asset: null, can_group: false, candidates: [] }); fixture.detectChanges();
    const inline = root.querySelector<HTMLElement>('[data-logical-asset]')!;
    expect(inline.tagName).toBe('SECTION');
    expect(root.querySelector('details, summary')).toBeNull();
    expect(inline.textContent).toContain('logical_assets.title');
    expect(inline.textContent).toContain('logical_assets.no_candidates');
    const help = root.querySelector<HTMLButtonElement>('[data-related-list] app-context-help button')!;
    expect(help.getAttribute('aria-label')).toBe('related_files.help_title');
    expect(help.textContent!.trim()).toBe('help_outline');
  });
});
