import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationStart, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { KeywordCatalogComponent } from './keyword-catalog.component';
import { GalleryStore } from './gallery.store';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

describe('Manual keyword catalog ownership and captured changes', () => {
  let fixture: ComponentFixture<KeywordCatalogComponent>;
  let component: KeywordCatalogComponent;
  let http: HttpTestingController;
  let state: ReturnType<typeof signal<{ owner: string; edition: boolean }>>;
  let token: string;
  let events: Subject<NavigationStart>;
  let refresh: ReturnType<typeof vi.fn>;
  let updateFilter: ReturnType<typeof vi.fn>;
  const catalog = { items: [{ tag: 'animals/cat', count: 2, typed: 1, imported: 1, unrecorded: 0 }], total: 1, next_after: null };
  const preview = { source: 'animals/cat', target: 'zoo/cat', paths: ['/a.jpg', '/b.jpg'], renamed: 1,
    merged: 1, ai_matches: 0, removed: 0, preview_token: 'signed-preview', expires_at: 9999999999 };

  function build(edition = true): void {
    state = signal({ owner: 'alice', edition }); token = 'token-a'; events = new Subject();
    refresh = vi.fn().mockResolvedValue(undefined); updateFilter = vi.fn().mockResolvedValue(undefined);
    TestBed.configureTestingModule({ imports: [KeywordCatalogComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), ApiService,
      { provide: AuthService, useValue: { status: state, identity: computed(() => state().owner), isEdition: computed(() => state().edition), get token() { return token; } } },
      { provide: Router, useValue: { url: '/', events } },
      { provide: GalleryStore, useValue: { updateFilter, refreshPaths: refresh, filters: signal({ tag: '' }), currentAlbum: signal(null) } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
    ] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(KeywordCatalogComponent); component = fixture.componentInstance;
    fixture.detectChanges();
  }
  async function open(): Promise<void> {
    component.toggle(true);
    http.expectOne(request => request.url === '/api/manual_tags/catalog' && request.params.get('limit') === '50').flush(catalog);
    await fixture.whenStable(); fixture.detectChanges();
  }
  async function capture(): Promise<void> {
    component.manage('animals/cat'); component.target.set('zoo/cat');
    const pending = component.preview(false);
    const request = http.expectOne('/api/manual_tags/manage/preview');
    expect(request.request.body).toEqual({ source: 'animals/cat', target: 'zoo/cat' });
    request.flush(preview); await pending; fixture.detectChanges();
  }
  afterEach(() => { fixture.destroy(); http.verify(); });

  it('loads nothing until opened, retains full identities/counts and allows read-only filtering', async () => {
    build(false); http.expectNone(() => true);
    await open();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-keyword-filter]')?.textContent).toContain('animals/cat');
    expect(root.querySelector('[data-keyword-filter]')?.textContent).toContain('2');
    expect(root.querySelector('[data-keyword-manage]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-keyword-filter]')!.click();
    expect(updateFilter).toHaveBeenCalledExactlyOnceWith('tag', 'animals/cat');
    await component.preview(true); await component.apply();
    http.expectNone(request => request.method === 'POST');
  });

  it('opens from its native disclosure and closes with Escape returning focus to its summary', async () => {
    build(false); await fixture.whenStable();
    const panel = fixture.nativeElement.querySelector('[data-keyword-catalog]') as HTMLDetailsElement;
    const trigger = panel.querySelector('summary')!;
    const opened = new Promise<void>(resolve => panel.addEventListener('toggle', () => resolve(), { once: true }));
    trigger.click(); await opened;
    expect(panel.open).toBe(true); expect(component.opened()).toBe(true);
    http.expectOne(request => request.url === '/api/manual_tags/catalog').flush(catalog);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(panel.open).toBe(true); expect(component.opened()).toBe(true);
    const input = panel.querySelector<HTMLInputElement>('[data-keyword-search]')!;
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    expect(panel.open).toBe(false); expect(component.opened()).toBe(false);
    expect(document.activeElement).toBe(trigger);
    http.expectNone(request => request.method === 'POST');
  });

  it('separates read-only preview from confirmed change and repairs the exact accepted paths', async () => {
    build(); await open(); await capture();
    http.expectNone('/api/manual_tags/manage/apply');
    expect(refresh).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('[data-keyword-preview]')).not.toBeNull();
    expect(document.activeElement).toBe(fixture.nativeElement.querySelector('[data-keyword-apply]'));
    const pending = component.apply();
    const request = http.expectOne('/api/manual_tags/manage/apply');
    expect(request.request.body).toEqual({ source: 'animals/cat', target: 'zoo/cat', preview_token: 'signed-preview' });
    request.flush({ source: 'animals/cat', target: 'zoo/cat', changed: 2 });
    const reload = await vi.waitFor(() => http.expectOne(request => request.url === '/api/manual_tags/catalog'));
    reload.flush(catalog);
    await pending;
    expect(refresh).toHaveBeenCalledExactlyOnceWith(['/a.jpg', '/b.jpg']);
    expect(component.result()?.changed).toBe(2);
    expect(component.plan()).toBeNull();
    expect(document.activeElement).toBe(fixture.nativeElement.querySelector('[data-keyword-search]'));
  });

  it('refuses old previews immediately after owner/token changes before auth effects settle', async () => {
    build(); await open(); await capture();
    token = 'token-b';
    await component.apply();
    http.expectNone('/api/manual_tags/manage/apply');
    state.set({ owner: 'bob', edition: true });
    await component.apply(); await component.load();
    http.expectNone(() => true);
    TestBed.tick();
    expect(component.plan()).toBeNull(); expect(component.catalog()).toBeNull();
  });

  it('refuses a confirmation after the draft target changed and requires another preview', async () => {
    build(); await open(); await capture();
    component.target.set('different/cat');
    await component.apply();
    http.expectNone('/api/manual_tags/manage/apply');
    const pending = component.preview(false);
    const request = http.expectOne('/api/manual_tags/manage/preview');
    expect(request.request.body.target).toBe('different/cat');
    request.flush({ ...preview, target: 'different/cat' }); await pending;
    expect(component.plan()?.target).toBe('different/cat');
  });

  it('cancels obsolete discovery reads on navigation and does not treat them as an empty catalog', async () => {
    build(); component.toggle(true);
    const request = http.expectOne(request => request.url === '/api/manual_tags/catalog');
    events.next(new NavigationStart(1, '/photo?path=a'));
    expect(request.cancelled).toBe(true);
    await Promise.resolve(); fixture.detectChanges();
    expect(component.catalog()).toBeNull(); expect(component.opened()).toBe(false);
    await component.load(); http.expectNone(() => true);
  });

  it('keeps an uncertain apply disabled until explicit read recovery and never resubmits it', async () => {
    build(); await open(); await capture();
    const pending = component.apply();
    http.expectOne('/api/manual_tags/manage/apply').flush({}, { status: 503, statusText: 'Unavailable' });
    await pending;
    expect(component.uncertain()).toBe(true);
    expect(refresh).toHaveBeenCalledOnce();
    await component.apply(); await component.preview(false);
    http.expectNone(request => request.method === 'POST');
    const recovering = component.load();
    const read = http.expectOne(request => request.url === '/api/manual_tags/catalog');
    expect(read.request.method).toBe('GET'); read.flush(catalog); await recovering;
    expect(component.uncertain()).toBe(false); expect(component.plan()).toBeNull();
  });

  it('does not cancel an accepted apply on navigation and retains same-owner repair without old UI', async () => {
    build(); await open(); await capture();
    const pending = component.apply();
    const request = http.expectOne('/api/manual_tags/manage/apply');
    events.next(new NavigationStart(1, '/photo?path=a'));
    expect(request.cancelled).toBe(false);
    request.flush({ source: 'animals/cat', target: 'zoo/cat', changed: 2 }); await pending;
    expect(refresh).toHaveBeenCalledExactlyOnceWith(['/a.jpg', '/b.jpg']);
    expect(component.result()).toBeNull(); expect(component.plan()).toBeNull();
    http.expectNone(() => true);
  });

  it('previews removal with a null target and leaves definite refusals editable', async () => {
    build(); await open(); component.manage('animals/cat');
    const pending = component.preview(true);
    const read = http.expectOne('/api/manual_tags/manage/preview');
    expect(read.request.body).toEqual({ source: 'animals/cat', target: null });
    read.flush({ ...preview, target: null, removed: 2 }); await pending;
    const apply = component.apply();
    http.expectOne('/api/manual_tags/manage/apply').flush({}, { status: 422, statusText: 'Refused' });
    await apply; http.expectNone(request => request.url === '/api/manual_tags/catalog');
    expect(component.error()).toBe(true);
    expect(component.uncertain()).toBe(false); expect(component.plan()).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
    component.manage('animals/cat'); expect(component.source()).toBe('animals/cat');
  });

  it('requests the next catalog cursor and pages the captured affected paths', async () => {
    build(); await open();
    const paging = component.load('animals/cat');
    const read = http.expectOne(request => request.url === '/api/manual_tags/catalog');
    expect(read.request.params.get('after')).toBe('animals/cat');
    read.flush({ ...catalog, items: [{ ...catalog.items[0], tag: 'zoo' }] }); await paging;
    component.manage('zoo'); component.target.set('park');
    const pending = component.preview(false);
    const paths = Array.from({ length: 26 }, (_, index) => `/photo-${index}.jpg`);
    http.expectOne('/api/manual_tags/manage/preview').flush({ ...preview, source: 'zoo', target: 'park', paths }); await pending;
    expect(component.previewPaths()).toEqual(paths.slice(0, 25));
    component.targetPage.set(1); expect(component.previewPaths()).toEqual([paths[25]]);
  });
});
