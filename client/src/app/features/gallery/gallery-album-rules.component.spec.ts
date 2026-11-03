import { HttpClient } from '@angular/common/http';
import fr from '../../../../../i18n/translations/fr.json';
import en from '../../../../../i18n/translations/en.json';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, NavigationStart } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { Album, AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { DEFAULT_FILTERS } from './gallery-filters.util';
import { GalleryAlbumRulesComponent } from './gallery-album-rules.component';

const album: Album = { id: 7, name: 'Keepers', description: '', is_smart: true, smart_filter_json: JSON.stringify({ camera: 'Canon' }), cover_photo_path: null, first_photo_path: null, is_shared: false, scoring_context: null, photo_count: 3, created_at: '', updated_at: '' };
function build(defaultType = '', localized = false) {
  let token = 'session-a';
  const status = signal({ user_id: 'alice' });
  const edition = signal(true);
  const filters = signal({ ...DEFAULT_FILTERS, camera: 'Nikon', hide_details: false, hide_blinks: false });
  const currentAlbum = signal<Album | null>({ ...album });
  const store = { filters, currentAlbum, config: signal(defaultType ? { defaults: { type: defaultType, sort: 'aggregate', sort_direction: 'DESC' } } : null), temporaryReviewQueue: signal(false), pinnedPaths: signal<string[] | null>(null), restoreAlbumRules: vi.fn(async value => { filters.set({ ...value, page: 1 }); }) };
  const albums = { get: vi.fn(() => of({ ...album })), update: vi.fn((_id: number, patch: { smart_filter_json: string }) => of({ ...album, ...patch })) };
  TestBed.configureTestingModule({ imports: [GalleryAlbumRulesComponent], providers: [
    provideRouter([]), { provide: GalleryStore, useValue: store }, { provide: AlbumService, useValue: albums },
    { provide: AuthService, useValue: { status, isEdition: edition, identity: () => status().user_id, get token() { return token; } } },
    ...(localized ? [I18nService, { provide: HttpClient, useValue: { get: vi.fn(() => of(fr)) } }] : [{ provide: I18nService, useValue: { translations: () => ({}), t: (key: string) => key } }]),
  ] });
  const fixture = TestBed.createComponent(GalleryAlbumRulesComponent); fixture.componentRef.setInput('active', true); fixture.detectChanges();
  const root: HTMLElement = fixture.nativeElement;
  const click = (selector: string) => { root.querySelector<HTMLButtonElement>(selector)!.click(); fixture.detectChanges(); };
  const settle = async () => { await fixture.whenStable(); fixture.detectChanges(); };
  return { fixture, root, click, settle, store, albums, status, edition, rotate: () => { token = 'session-b'; } };
}

describe('Captured album rule editing', () => {
  afterEach(() => TestBed.resetTestingModule());
  it('uses the configured historical type baseline while preserving an explicitly saved All photos rule', async () => {
    const { fixture, root, store, albums, settle } = build('portrait');
    store.filters.set({ ...store.filters(), camera: 'Canon', type: 'portrait' }); await settle();
    expect(root.querySelector<HTMLButtonElement>('[data-album-preview]')!.disabled).toBe(true);
    store.filters.update(value => ({ ...value, type: '' })); await settle();
    expect(root.querySelector<HTMLButtonElement>('[data-album-preview]')!.disabled).toBe(false);
    store.currentAlbum.set({ ...album, smart_filter_json: JSON.stringify({ camera: 'Canon', type: '' }) }); await settle();
    expect(root.querySelector<HTMLButtonElement>('[data-album-preview]')!.disabled).toBe(true);
    expect(albums.update).not.toHaveBeenCalled(); fixture.destroy();
  });
  it('refuses preview, reset and reload after its collection is parked or navigation is pending', async () => {
    const { fixture, click, settle, root, store, albums } = build();
    fixture.componentRef.setInput('active', false); await settle();
    click('[data-album-rules] summary');
    expect(root.querySelector<HTMLButtonElement>('[data-album-preview]')!.disabled).toBe(true);
    click('[data-album-preview]'); click('[data-album-reset]');
    expect(root.querySelector('[data-album-rule-preview]')).toBeNull();
    expect(store.restoreAlbumRules).not.toHaveBeenCalled(); expect(albums.get).not.toHaveBeenCalled(); expect(albums.update).not.toHaveBeenCalled();
  });
  it('previews without writing, then saves exactly the captured rule fields and keeps the current view', async () => {
    const { root, click, settle, store, albums } = build();
    click('[data-album-rules] summary'); click('[data-album-preview]');
    expect(root.querySelector('[data-album-rule-preview]')).not.toBeNull(); expect(albums.update).not.toHaveBeenCalled();
    const before = store.filters(); click('[data-album-apply]'); await settle();
    expect(albums.get).toHaveBeenCalledWith(7); expect(albums.update).toHaveBeenCalledOnce();
    const saved = JSON.parse(albums.update.mock.calls[0][1].smart_filter_json);
    expect(saved.camera).toBe('Nikon'); expect(saved.hide_details).toBeUndefined(); expect(saved.hide_blinks).toBeUndefined();
    expect(store.filters()).toBe(before); expect(store.currentAlbum()?.smart_filter_json).toBe(albums.update.mock.calls[0][1].smart_filter_json);
    expect(root.querySelector('[data-album-rule-preview]')).toBeNull();
  });
  it('refuses changed saved rules and reloads metadata without resetting current refinements', async () => {
    const { root, click, settle, store, albums } = build();
    albums.get.mockReturnValue(of({ ...album, smart_filter_json: JSON.stringify({ camera: 'Sony' }) }));
    click('[data-album-rules] summary'); click('[data-album-preview]'); click('[data-album-apply]'); await settle();
    expect(albums.update).not.toHaveBeenCalled(); expect(root.querySelector('[role=alert]')?.textContent).toContain('albums.rules.conflict');
    const before = store.filters(); click('[data-album-reload]'); await settle();
    expect(store.currentAlbum()?.smart_filter_json).toContain('Sony'); expect(store.filters()).toBe(before);
  });
  it.each(['criteria', 'token', 'navigation'])('refuses a captured save when %s changes before the preflight finishes', async ending => {
    const { click, settle, store, albums, rotate } = build();
    const read = new Subject<Album>(); albums.get.mockReturnValue(read);
    click('[data-album-rules] summary'); click('[data-album-preview]'); click('[data-album-apply]');
    if (ending === 'criteria') store.filters.update(f => ({ ...f, camera: 'New draft' }));
    else if (ending === 'token') rotate();
    else (TestBed.inject(Router).events as Subject<unknown>).next(new NavigationStart(1, '/albums'));
    read.next({ ...album }); read.complete(); await settle();
    expect(albums.update).not.toHaveBeenCalled();
  });
  it('requires reloading after an uncertain write and does not blindly retry', async () => {
    const { root, click, settle, albums } = build();
    albums.update.mockReturnValue(throwError(() => new Error('lost response')));
    click('[data-album-rules] summary'); click('[data-album-preview]'); click('[data-album-apply]'); await settle();
    expect(root.querySelector('[role=alert]')?.textContent).toContain('albums.rules.uncertain');
    expect(root.querySelector<HTMLButtonElement>('[data-album-apply]')!.disabled).toBe(true);
    click('[data-album-apply]'); expect(albums.update).toHaveBeenCalledOnce();
    click('[data-album-reload]'); await settle(); expect(root.querySelector('[data-album-rule-preview]')).toBeNull();
  });
  it('reconciles a successful write after navigation without replacing the working filters', async () => {
    const { click, settle, store, albums } = build();
    const write = new Subject<Album & { smart_filter_json: string }>(); albums.update.mockReturnValue(write);
    click('[data-album-rules] summary'); click('[data-album-preview]'); click('[data-album-apply]');
    await Promise.resolve();
    const saved = { ...album, smart_filter_json: albums.update.mock.calls[0][1].smart_filter_json };
    store.filters.update(value => ({ ...value, camera: 'New draft' }));
    (TestBed.inject(Router).events as Subject<unknown>).next(new NavigationStart(1, '/album/7?camera=New'));
    write.next(saved); write.complete(); await settle();
    expect(store.currentAlbum()?.smart_filter_json).toBe(saved.smart_filter_json);
    expect(store.filters().camera).toBe('New draft');
  });
  it('resets supported rules while retaining display settings, and blocks unrepresentable modes', async () => {
    const { root, click, settle, store, albums } = build();
    click('[data-album-rules] summary'); click('[data-album-reset]'); await settle();
    expect(store.filters()).toMatchObject({ camera: 'Canon', hide_details: false, hide_blinks: false, page: 1 });
    expect(albums.update).not.toHaveBeenCalled();
    store.currentAlbum.set({ ...album, smart_filter_json: JSON.stringify({ favorites_only: true }) });
    store.filters.update(f => ({ ...f, favorites_only: false, hide_rejected: true })); await settle();
    click('[data-album-reset]'); await settle();
    expect(store.filters()).toMatchObject({ favorites_only: true, hide_rejected: false });
    store.filters.update(f => ({ ...f, camera: 'Other', gps_lat: '0', gps_lng: '0' })); await settle();
    expect(root.querySelector<HTMLButtonElement>('[data-album-preview]')!.disabled).toBe(true);
    expect(root.querySelector<HTMLButtonElement>('[data-album-reset]')!.disabled).toBe(true);
  });
  it('distinguishes manual membership and exposes no saved-rule write controls to read-only users', async () => {
    const { root, click, settle, store, edition } = build(); edition.set(false); await settle();
    click('[data-album-rules] summary'); expect(root.querySelector('[data-album-preview]')).toBeNull();
    store.currentAlbum.set({ ...album, is_smart: false }); await settle();
    expect(root.textContent).toContain('albums.rules.manual_hint'); expect(root.querySelector('[data-album-reset]')).toBeNull();
  });
});

// Real bundles and translation service: labels and literal rule values have different authority.
describe('Localized saved album rules', () => {
  afterEach(() => TestBed.resetTestingModule());
  it('updates table and captured preview labels on language changes without translating user text', async () => {
    const { fixture, root, store, click, settle } = build('', true);
    const i18n = TestBed.inject(I18nService); i18n.locale.set('fr'); await i18n.load();
    store.currentAlbum.update(album => ({ ...album!, smart_filter_json: JSON.stringify({ camera: 'Canon', tag: 'true', search: 'gallery.camera', min_aesthetic: '3', favorites_only: true }) }));
    store.filters.update(f => ({ ...f, camera: 'gallery.camera', tag: 'false', search: 'albums.title', min_aesthetic: '6', favorites_only: false }));
    await settle(); click('[data-album-rules] summary'); click('[data-album-preview]'); await settle();
    const headers = () => Array.from(root.querySelectorAll('tbody th')).map(node => node.textContent!.trim());
    expect(headers()).toContain(fr.gallery.camera);
    expect(headers()).toContain(fr.gallery.aesthetic_range + ' ≥');
    const preview = () => root.querySelector('[data-album-rule-preview] ul')!.textContent!;
    expect(preview()).toContain(fr.gallery.camera + ': Canon');
    expect(preview()).toContain(fr.gallery.aesthetic_range + ' ≥: 3');
    expect(preview()).toContain('gallery.camera'); expect(preview()).toContain('albums.title');
    expect(preview()).toContain('true → false');
    expect(root.querySelector('tbody')!.textContent).toContain(fr.organization_history.yes);
    vi.mocked(TestBed.inject(HttpClient).get).mockReturnValue(of(en)); i18n.locale.set('en'); await i18n.load(); await settle();
    expect(headers()).toContain(en.gallery.camera); expect(headers()).not.toContain(fr.gallery.camera);
    expect(preview()).toContain(en.gallery.camera + ': Canon');
    expect(preview()).toContain(en.gallery.aesthetic_range + ' ≥: 3');
    expect(preview()).toContain('true → false'); expect(preview()).toContain('gallery.camera');
    fixture.destroy();
  });
});
