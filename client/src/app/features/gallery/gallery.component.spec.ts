import type { Photo } from '../../shared/models/photo.model';
import type { Mock } from 'vitest';
import { ComponentFixture, DeferBlockState, TestBed } from '@angular/core/testing';
import { ChangeDetectorRef, Component, computed, DebugElement, DestroyRef, signal, WritableSignal } from '@angular/core';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { RouterTestingHarness } from '@angular/router/testing';
import { GALLERY_REVISIT, GalleryReuseStrategy } from '../../core/gallery-reuse.strategy';
import { ActivatedRoute, Event as RouterEvent, NavigationEnd, NavigationStart, provideRouter, RouteReuseStrategy, Router, RouterOutlet } from '@angular/router';
import { By } from '@angular/platform-browser';
import { ControlPopoverComponent } from '../../shared/components/control-popover/control-popover.component';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { KeyboardMappingService, KEYMAP_STORAGE_KEY } from '../../core/services/keyboard-mapping.service';
import { GalleryPhotoMenuComponent } from './gallery-photo-menu.component';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { HttpErrorResponse } from '@angular/common/http';
import { defer, filter, finalize, firstValueFrom, Subject, of, throwError } from 'rxjs';
import { MatContextMenuTrigger, MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatSelect, MatSelectModule } from '@angular/material/select';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatTooltip } from '@angular/material/tooltip';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { ScrollDispatcher } from '@angular/cdk/scrolling';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatSidenav, MatSidenavContainer, MatSidenavContent } from '@angular/material/sidenav';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { buildApiParams, buildSyncParams, DISPLAY_OPTIONS_KEY } from './gallery-filters.util';
import { ApiService } from '../../core/services/api.service';
import { MAX_REFRESH_PATHS, PhotoActionsService } from '../../core/services/photo-actions.service';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { NOTICE_DISMISSALS_KEY } from './notice-dismiss.util';
import { ComparisonSessionService } from './comparison-session.service';
import { GalleryComponent } from './gallery.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { SlideshowComponent } from './slideshow.component';
import { I18N } from '../../core/i18n/keys';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';
import { MAX_COMPARE_QUEUE } from './comparison-slots.util';
import { gridColumnCount } from './gallery-rows.util';
import { ScanService } from '../../core/services/scan.service';
import { UndoService } from '../../core/services/undo.service';
import { SequenceKind } from '../../core/services/sequence-override.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { privateImageSessionKey, resetPrivateImageSession } from '../../shared/utils/private-image-session';
import { makePhoto } from '../../../testing/photo.fixture';

@Component({ template: 'Photo route' })
class MenuPhotoRoute {}

// The selection bar's desktop Actions menu lives in a CDK overlay, so its items are
// reached through the overlay container rather than through the bar.
const openMenuPanels = () => [...document.querySelectorAll<HTMLElement>('.cdk-overlay-container .mat-mdc-menu-panel')];
const menuItemLabel = (item: Element) => item.querySelector('.mat-mdc-menu-item-text')?.textContent?.trim() ?? '';
/** A panel's own entries in order: each item's label, and '─' for a divider. */
const menuEntries = (panel: HTMLElement) => [...panel.querySelectorAll('.mat-mdc-menu-item, mat-divider')]
  .map(entry => entry.tagName === 'MAT-DIVIDER' ? '─' : menuItemLabel(entry));
const menuItem = (panel: HTMLElement, label: string) =>
  [...panel.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-item')].find(item => menuItemLabel(item) === label) ?? null;
function openSelectionActions(f: ComponentFixture<unknown>): HTMLElement {
  (f.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-selection-bar] [data-selection-more]')!.click();
  f.detectChanges();
  return openMenuPanels().at(-1)!;
}
function openSelectionSubmenu(f: ComponentFixture<unknown>, panel: HTMLElement, label: string): HTMLElement {
  menuItem(panel, label)!.click();
  f.detectChanges();
  return openMenuPanels().at(-1)!;
}
/** A closed mat-menu detaches its overlay on a timer, even with animations off. */
const settle = () => new Promise<void>(resolve => setTimeout(resolve));
const keydown = (target: Element, key: string, keyCode: number) => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  Object.defineProperty(event, 'keyCode', { get: () => keyCode });
  target.dispatchEvent(event);
  return event;
};

describe('GalleryComponent', () => {
  let component: GalleryComponent;

   
  let mockStore: any;
  let mockApi: { thumbnailUrl: Mock; post: Mock; downloadUrl: Mock; getRaw: Mock };
  let mockAuth: Record<string, unknown>;
  // `translations` and `lang` are only read once the real template renders:
  // the translate pipe subscribes to the bundle even when `t` is stubbed.
  let mockI18n: {
    t: Mock;
    translations: WritableSignal<Record<string, unknown>>;
    lang: WritableSignal<string>;
  };
  let routeMock: { snapshot: { paramMap: { get: Mock }; queryParams: Record<string, string> } };
  let outletMock: { attachEvents: Subject<unknown>; detachEvents: Subject<unknown> };

  it('clears its slideshow state when the gallery is destroyed', () => {
    mockStore.slideshowActive.set(true);
    component.ngOnDestroy();
    expect(mockStore.slideshowActive()).toBe(false);
  });

  it('releases a stale side-drawer inset for mobile or a closed desktop drawer', () => {
    const desktop = signal(true);
    Object.defineProperty(component, 'isDesktop', { value: desktop });
    const geometry = component as unknown as { noticeInsetPx: WritableSignal<number>; noticeRightPx: () => number };
    mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tooltip_mode: 'hover' }));
    mockStore.filterDrawerOpen.set(true);
    geometry.noticeInsetPx.set(320);
    expect(geometry.noticeRightPx()).toBe(336);
    desktop.set(false);
    expect(geometry.noticeRightPx()).toBe(8);
    desktop.set(true);
    mockStore.filterDrawerOpen.set(false);
    expect(geometry.noticeRightPx()).toBe(16);
  });

  it('adds a literal tag constraint without replacing existing tag alternatives', () => {
    mockStore.filters.update((f: GalleryFilters) => ({ ...f, album_id: '8', tag_groups: '{"any":["a","b"]}' }));
    (component as any).navigateTag({ tag: 'coast,ridge OR 夜景', scope: 'collection' });
    expect(mockStore.updateFilter).toHaveBeenCalledWith('tag_groups', '{"any":["a","b"],"all":["coast,ridge OR 夜景"]}');
  });

  it('refuses collection tag refinement for captured lists and Similar Photos', () => {
    mockStore.pinnedPaths.set(['/a.jpg']);
    (component as any).navigateTag({ tag: 'trip', scope: 'collection' });
    mockStore.pinnedPaths.set(null);
    mockStore.filters.update((f: GalleryFilters) => ({ ...f, similar_to: '/source.jpg' }));
    (component as any).navigateTag({ tag: 'trip', scope: 'collection' });
    expect(mockStore.updateFilter).not.toHaveBeenCalled();
  });

  beforeEach(async () => {
    mockStore = {
      filters: signal<GalleryFilters>({ ...DEFAULT_FILTERS }),
      types: signal([
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 200 },
        { id: 'macro', label: 'Macro', count: 50 },
      ]),
      photos: signal([]),
      focusedPath: signal<string | null>(null),
      total: signal(0),
      photoTotal: () => mockStore.total(),
      collapseStacks: signal(true),
      toggleStackCollapse: vi.fn(),
      loading: signal(false),
      isPageAppending: vi.fn(() => false),
      loadError: signal(false),
      loadErrorKey: signal<string | undefined>(undefined),
      hasMore: signal(false),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      config: signal(null),
      activeFilterCount: signal(0),
      filterDrawerOpen: signal(false),
      reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(), viewChangeClears: signal(0),
      currentAlbum: signal(null),
      temporaryReviewQueue: signal(false),
      initializing: signal(false),
      galleryMounts: signal(0),
      galleryMode: signal('mosaic'),
      setGalleryMode: vi.fn((mode: string) => mockStore.galleryMode.set(mode)),
      cardWidth: signal(300),
      virtualScroll: signal(false),
      setFilterDrawerOpen: vi.fn(),
      loadConfig: vi.fn(() => Promise.resolve(true)),
      loadFilterOptions: vi.fn(() => Promise.resolve()),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
      loadPhotos: vi.fn(() => Promise.resolve()),
      reloadPhotos: vi.fn(() => Promise.resolve()),
      parkListingReads: vi.fn(),
      resumeListingReads: vi.fn(() => Promise.resolve()),
      updateFilter: vi.fn(() => Promise.resolve()),
      resetFilters: vi.fn(() => Promise.resolve()),
      nextPage: vi.fn(() => Promise.resolve()),
      toggleFavorite: vi.fn(),
      toggleRejected: vi.fn(),
      selectedPaths: signal(new Set<string>()),
      excludedPaths: signal(new Set<string>()),
      selectionScope: signal<'paths' | 'view'>('paths'),
      viewScopeSelected: signal(false),
      canScopeSelectionToView: signal(true),
      selectionCount: signal(0),
      selectedLoadedPaths: computed(() => {
        const selected = mockStore.selectedPaths() as Set<string>;
        const excluded = mockStore.excludedPaths() as Set<string>;
        return (mockStore.photos() as { path: string }[])
          .filter(p => (mockStore.viewScopeSelected() ? !excluded.has(p.path) : selected.has(p.path)))
          .map(p => p.path);
      }),
      toggleSelection: vi.fn(),
      selectAll: vi.fn(),
      selectAllLoaded: vi.fn(),
      selectWholeView: vi.fn(),
      invertSelection: vi.fn(),
      clearSelection: vi.fn(),
      restoreSelection: vi.fn(),
      restoreSnapshot: vi.fn(() => Promise.resolve()),
      countInView: vi.fn(() => Promise.resolve(650)),
      pathsInView: vi.fn(() => Promise.resolve([] as string[])),
      filterPayload: vi.fn(() => ({ page: '1' })),
      reviewProgress: signal(null),
      reviewPercent: signal(0),
      reviewBookmark: signal(null),
      continueReview: vi.fn(() => Promise.resolve(null)),
      viewSnapshot: signal(null),
      pinnedPaths: signal<string[] | null>(null),
      clearPinned: vi.fn(() => Promise.resolve()),
      filterKey: vi.fn((f?: GalleryFilters) => JSON.stringify(buildApiParams(f ?? mockStore.filters(), false, undefined))),
      reviewProgressKey: vi.fn(() => {
        const scope = buildApiParams(mockStore.filters(), false, undefined);
        for (const key of ['page', 'per_page', 'sort', 'sort_direction']) delete scope[key];
        return JSON.stringify(scope);
      }),
      hiddenSummary: signal({ total: 0, blinks: 0, bursts: 0, duplicates: 0 }),
      hiddenFiltersStash: signal(null),
      showAllHidden: vi.fn(),
      takeTransientRestore: vi.fn((): Record<string, boolean> => ({})),
      restoreHidden: vi.fn(),
      readGallerySessionQuery: vi.fn(() => null),
      applySessionQuery: vi.fn(),
      saveSessionQuery: vi.fn(),
      updateFilters: vi.fn(() => Promise.resolve()),
      setRating: vi.fn(),
      batchFavorite: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      batchReject: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      batchRating: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      patchSequenceOverride: vi.fn(),
      removePhotos: vi.fn(),
      // Read only once the real template renders -- the toolbar, the filter
      // sidebar and the slideshow all pull off the store directly.
      slideshowActive: signal(false),
      patterns: signal([]),
      colorTemps: signal([]),
      hueBuckets: signal([]),
      metricRanges: signal({}),
      metricRangesByColumn: signal({}),
      ensureMetricRanges: vi.fn(() => Promise.resolve()),
      gpsLocationName: signal(''),
      viewFilterParams: signal({}),
    };

    mockApi = {
      thumbnailUrl: vi.fn((path: string) => `/thumbnail?path=${path}`),
      post: vi.fn(() => of({ success: true, overridden: 0, skipped: 0, kind: null })),
      downloadUrl: vi.fn((path: string) => `/download?path=${path}`),
      getRaw: vi.fn(() => of(new Blob(['x']))),
    };

    const authStatus = signal<{ user_id: string }>({ user_id: "editor" });
    mockAuth = {
      status: authStatus,
      identity: vi.fn(() => authStatus().user_id),
      session: computed(() => authStatus()?.user_id ?? null),
      isEdition: vi.fn(() => false),
      downloadProfiles: vi.fn(() => []),
      hasFeature: vi.fn(() => false),
      isMultiUser: vi.fn(() => false),
      isSuperadmin: vi.fn(() => false),
      editionPasswordRequired: vi.fn(() => false),
      loginPasswordRequired: vi.fn(() => false),
    };

    mockI18n = {
      t: vi.fn((key: string) => key),
      translations: signal<Record<string, unknown>>({}),
      lang: signal('en'),
    };

    routeMock = { snapshot: { paramMap: { get: vi.fn(() => null) }, queryParams: {} } };
    outletMock = { attachEvents: new Subject(), detachEvents: new Subject() };

    await TestBed.configureTestingModule({
      imports: [GalleryComponent],
      providers: [
        provideNativeDateAdapter(),
        // Tooltip hides wait for an animationend jsdom never fires unless animations are off.
        { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
        { provide: GalleryStore, useValue: mockStore },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        {
          provide: AlbumService,
          useValue: {
            list: vi.fn(() => of({ albums: [] })),
            get: vi.fn(() => of({})),
            addPhotos: vi.fn(() => of({ added: 0 })),
          },
        },
        { provide: ActivatedRoute, useValue: routeMock },
        { provide: ScanService, useValue: { canLaunch: signal(false), openLauncher: vi.fn(() => Promise.resolve(false)) } },
        { provide: RouterOutlet, useValue: outletMock },
        { provide: ChangeDetectorRef, useValue: { detectChanges: vi.fn() } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: MatBottomSheet, useValue: { open: vi.fn() } },
        { provide: LiveAnnouncer, useValue: { announce: vi.fn(() => Promise.resolve()) } },
        // Returns a ref stub, not undefined: UndoService reads onAction() /
        // afterDismissed() off whatever open() hands back.
        {
          provide: MatSnackBar,
          useValue: {
            open: vi.fn(() => ({
              onAction: () => new Subject<void>(),
              afterDismissed: () => new Subject<void>(),
            })),
          },
        },
      ],
    }).compileComponents();
    component = TestBed.runInInjectionContext(() => new GalleryComponent());
  });

  it.each(['navigation', 'edition'] as const)('closes the captured rating preview after %s invalidates it without applying', async ending => {
    (mockAuth['isEdition'] as Mock).mockReturnValue(true);
    mockStore.selectedPaths.set(new Set(['/rating.jpg'])); mockStore.selectionCount.set(1);
    mockStore.photos.set([{ path: '/rating.jpg', filename: 'rating.jpg', star_rating: 0 }]);
    mockStore.batchRatingPaths = vi.fn();
    const closed = new Subject<number | undefined>();
    const ref = { afterClosed: () => closed, close: vi.fn(() => { closed.next(undefined); closed.complete(); }) };
    const open = TestBed.inject(MatDialog).open as Mock; open.mockReturnValue(ref);
    const operation = component.selectionActions.batchRate(3);
    await vi.waitFor(() => expect(open).toHaveBeenCalled()); TestBed.tick();
    if (ending === 'navigation') (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(22, '/albums'));
    else { (mockAuth['isEdition'] as Mock).mockReturnValue(false); (mockAuth['status'] as WritableSignal<unknown>).update(value => ({ ...(value as object), edition_authenticated: false })); TestBed.tick(); }
    await operation;
    expect(ref.close).toHaveBeenCalled(); expect(mockStore.batchRatingPaths).not.toHaveBeenCalled();
  });

  it('applies captured rating membership and wires rating-only Undo while preserving a newer selection', async () => {
    (mockAuth['isEdition'] as Mock).mockReturnValue(true);
    const paths = ['/rating-a.jpg', '/rating-b.jpg'];
    mockStore.selectedPaths.set(new Set(paths)); mockStore.selectionCount.set(2);
    mockStore.photos.set(paths.map((path, index) => ({ path, filename: path, star_rating: index * 4 })));
    const snapshot = new Map(paths.map((path, index) => [path, {
      is_favorite: false, is_rejected: false, is_kept: false, star_rating: index * 4,
    }]));
    let completeWrite!: (result: { snapshot: typeof snapshot; targeted: number; count: number }) => void;
    mockStore.batchRatingPaths = vi.fn(() => new Promise(resolve => { completeWrite = resolve; }));
    mockStore.restoreRatingSnapshot = vi.fn().mockResolvedValue(true);
    const register = vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(() => {});
    const closed = new Subject<number | undefined>();
    const open = TestBed.inject(MatDialog).open as Mock;
    open.mockReturnValue({ afterClosed: () => closed, close: vi.fn() });

    const operation = component.selectionActions.batchRate(3);
    await vi.waitFor(() => expect(open).toHaveBeenCalled());
    expect(open.mock.calls[0][1].data).toEqual(expect.objectContaining({
      paths, rating: 3, loaded: 2, wholeView: false,
      observed: [{ rating: 0, count: 1 }, { rating: 4, count: 1 }],
    }));
    expect(mockStore.batchRatingPaths).not.toHaveBeenCalled();
    closed.next(3); closed.complete();
    await vi.waitFor(() => expect(mockStore.batchRatingPaths).toHaveBeenCalledWith(paths, 3));
    mockStore.selectedPaths.set(new Set(['/newer.jpg'])); mockStore.selectionCount.set(1);
    completeWrite({ snapshot, targeted: 2, count: 2 }); await operation;

    expect(mockStore.selectedPaths()).toEqual(new Set(['/newer.jpg']));
    expect(mockStore.clearSelection).not.toHaveBeenCalled();
    expect(register).toHaveBeenCalledWith(expect.objectContaining({
      labelKey: 'gallery.selection.batch_rated', labelParams: { count: 2, rating: 3 },
    }));
    await register.mock.calls[0][0].undo();
    expect(mockStore.restoreRatingSnapshot).toHaveBeenCalledWith(snapshot, 3);
    expect([...mockStore.restoreSelection.mock.calls[0][0]]).toEqual(paths);
    expect(mockStore.restoreSnapshot).not.toHaveBeenCalled();
  });

  it('owns matching/group counts and shows exact item totals for an assistant-pinned list', () => {
    vi.spyOn(TestBed.inject(I18nService), 't').mockImplementation((key, params) => {
      if (key === I18N.gallery.photo_count) return `${params?.['count']} photos`;
      if (key === I18N.gallery.collection_totals_compact) return `${params?.['photos']} matching, ${params?.['items']} displayed`;
      return key;
    });
    mockStore.total.set(2);
    mockStore.photoTotal = signal(4);
    const fixture = TestBed.createComponent(GalleryComponent);
    const desktop = signal(true);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: desktop });
    fixture.detectChanges();
    const header = fixture.nativeElement.querySelector('[data-collection-header]') as HTMLElement;
    expect(header.textContent).toContain('4 matching, 2 displayed');
    const status = header.querySelector('[role="status"]');
    expect(status?.textContent).toContain('4 matching, 2 displayed');
    desktop.set(false); fixture.detectChanges();
    expect(status?.textContent).toContain('4 matching, 2 displayed');
    expect(header.querySelector('[role="status"]')).toBe(status);
    mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg']);
    fixture.detectChanges();
    expect(header.textContent).toContain('2 photos');
    expect(header.textContent).not.toContain('4 photos');
    expect(header.querySelector('[role="status"]')).toBe(status);
    expect(status?.textContent).toContain('2 photos');
    fixture.destroy();
  });

  describe('collection header stickiness', () => {
    function render() {
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const markers = Array.from(fixture.nativeElement.querySelectorAll('[data-collection-header]')) as HTMLElement[];
      return { fixture, bar: markers[0], criteria: markers[1], markers };
    }

    it('pins the bar row at every width and the criteria row only from lg, below the measured bar', () => {
      const { fixture, bar, criteria, markers } = render();
      expect(markers).toHaveLength(2);
      expect(bar.tagName).toBe('HEADER');
      expect(bar.classList).toContain('sticky');
      expect(bar.classList).toContain('top-0');
      expect(criteria.tagName).toBe('APP-GALLERY-CRITERIA');
      expect(bar.contains(criteria)).toBe(false);
      expect(bar.nextElementSibling).toBe(criteria);
      expect(criteria.classList).toContain('lg:sticky');
      expect(criteria.classList).not.toContain('sticky');
      expect(criteria.classList).toContain('lg:z-40');
      expect(criteria.className).toContain('bg-[var(--mat-sys-surface-container-lowest)]');
      const instance = fixture.componentInstance as unknown as { collectionBarHeight: WritableSignal<number> };
      instance.collectionBarHeight.set(61);
      fixture.detectChanges();
      expect(criteria.style.top).toBe('61px');
      fixture.destroy();
    });

    it('measures the criteria row with an observer of its own and pads the scroll by it from lg', () => {
      const observers: { callback: ResizeObserverCallback; targets: Element[] }[] = [];
      const spy = vi.spyOn(globalThis, 'ResizeObserver').mockImplementation(function (callback: ResizeObserverCallback) {
        const record = { callback, targets: [] as Element[] };
        observers.push(record);
        return { observe: (target: Element) => record.targets.push(target), unobserve: vi.fn(), disconnect: vi.fn() } as unknown as ResizeObserver;
      });
      try {
        const { fixture, criteria } = render();
        TestBed.tick();
        const criteriaObserver = observers.find(o => o.targets.includes(criteria));
        expect(criteriaObserver).toBeDefined();
        expect(criteriaObserver!.targets).toEqual([criteria]);
        criteria.getBoundingClientRect = () => ({ height: 48 }) as DOMRect;
        criteriaObserver!.callback([{ target: criteria } as unknown as ResizeObserverEntry], {} as ResizeObserver);
        const instance = fixture.componentInstance as unknown as { collectionCriteriaHeight(): number; lgDesktop: { setMatches(v: boolean): void } };
        expect(instance.collectionCriteriaHeight()).toBe(48);
        const content = fixture.nativeElement.querySelector('mat-sidenav-content') as HTMLElement;
        instance.lgDesktop.setMatches(true);
        fixture.detectChanges();
        expect(content.style.scrollPaddingTop).toBe('48px');
        instance.lgDesktop.setMatches(false);
        fixture.detectChanges();
        expect(content.style.scrollPaddingTop).toBe('0px');
        fixture.destroy();
      } finally {
        spy.mockRestore();
      }
    });

    it('pads the scroll by the bar below lg and by bar plus criteria from lg', () => {
      const { fixture } = render();
      const instance = fixture.componentInstance as unknown as {
        collectionBarHeight: WritableSignal<number>; collectionCriteriaHeight: WritableSignal<number>;
        collectionHeaderHeight(): number; lgDesktop: { setMatches(v: boolean): void };
      };
      instance.collectionBarHeight.set(61);
      instance.collectionCriteriaHeight.set(48);
      instance.lgDesktop.setMatches(false);
      expect(instance.collectionHeaderHeight()).toBe(61);
      instance.lgDesktop.setMatches(true);
      expect(instance.collectionHeaderHeight()).toBe(109);
      fixture.destroy();
    });
  });

  it('keeps stack expansion available locally to read-only users without filtering an exact pinned list', () => {
    mockAuth['isEdition'] = vi.fn(() => false);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const query = root.querySelector('[data-collection-query]')!;
    expect(query.querySelector('[data-stack-collapse]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-collection-options] button')!.click(); fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    overlay.querySelector<HTMLButtonElement>('[data-stack-collapse]')!.click();
    expect(mockStore.toggleStackCollapse).toHaveBeenCalledOnce();
    mockStore.pinnedPaths.set(['/a.jpg']);
    fixture.detectChanges();
    expect(overlay.querySelector('[data-stack-collapse]')).toBeNull();
    fixture.destroy();
  });

  it('reveals mobile search on request and returns focus when Escape collapses it', () => {
    const fixture = TestBed.createComponent(GalleryComponent);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(false) });
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const query = root.querySelector('[data-collection-query]')!;
    const button = root.querySelector<HTMLButtonElement>('button[aria-label="ui.filters.search"]')!;
    const input = query.querySelector('input')!;
    expect(query.classList.contains('!hidden')).toBe(true);
    button.click(); fixture.detectChanges();
    expect(query.classList.contains('!hidden')).toBe(false);
    input.focus();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); fixture.detectChanges();
    expect(query.classList.contains('!hidden')).toBe(true);
    expect(document.activeElement).toBe(button);
    mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, search: 'coast' })); fixture.detectChanges();
    expect(query.classList.contains('!hidden')).toBe(false);
    expect(input.value).toBe('coast');
    fixture.destroy(); root.remove();
  });

  it('uses the spare medium-width row for search and preserves it on Escape', () => {
    const fixture = TestBed.createComponent(GalleryComponent);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(false) });
    fixture.componentInstance['containerWidth'].set(556); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const query = root.querySelector('[data-collection-query]')!;
    expect(query.classList.contains('!hidden')).toBe(false);
    expect(root.querySelector('button[aria-label="ui.filters.search"]')).toBeNull();
    query.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); fixture.detectChanges();
    expect(query.classList.contains('!hidden')).toBe(false);
    fixture.componentInstance['containerWidth'].set(375); fixture.detectChanges();
    expect(query.classList.contains('!hidden')).toBe(true);
    expect(root.querySelector('button[aria-label="ui.filters.search"]')).not.toBeNull();
    fixture.destroy();
  });

  it('keeps Filters direct and gives Review and Display one lazy popover each', () => {
    mockStore.selectedPaths.set(new Set(['/selected.jpg'])); mockStore.selectionCount.set(1);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges(); TestBed.tick();
    const root = fixture.nativeElement as HTMLElement;
    expect((fixture.componentInstance as any).viewControls()).toBeDefined();
    expect(root.querySelectorAll('[data-collection-sort]')).toHaveLength(0);
    expect(root.querySelector('[data-gallery-layout]')).toBeNull();
    const filter = root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.gallery.filters}"]`)!;
    filter.click();
    expect(mockStore.setFilterDrawerOpen).toHaveBeenCalledExactlyOnceWith(true);
    root.querySelector<HTMLButtonElement>('[data-collection-options] button')!.click();
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    expect(overlay.querySelectorAll('[data-gallery-layout="grid"]')).toHaveLength(1);
    expect(overlay.querySelectorAll('[data-collection-sort]')).toHaveLength(1);
    expect([...mockStore.selectedPaths()]).toEqual(['/selected.jpg']);
    fixture.destroy();
  });

  it('keeps review commands out of search and closes Review only after Keep top succeeds', async () => {
    mockAuth['isEdition'] = vi.fn(() => true);
    mockStore.total.set(4);
    mockStore.photos.set([makePhoto({ path: '/a.jpg' })]);
    mockStore.selectBottomPercent = vi.fn().mockResolvedValueOnce(null).mockImplementationOnce(async () => {
      mockStore.selectedPaths.set(new Set(['/a.jpg'])); mockStore.selectionCount.set(1);
      return { paths: ['/a.jpg'], cut: 1, truncated: false };
    });
    const fixture = TestBed.createComponent(GalleryComponent);
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-collection-query] button')).toBeNull();
    const review = root.querySelector<HTMLButtonElement>('[data-collection-review] button')!;
    review.click(); fixture.detectChanges(); await fixture.whenStable();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    expect(overlay.querySelector('[data-stack-suggestions]')).not.toBeNull();
    overlay.querySelector<HTMLElement>('[data-keep-top-controls] summary')!.click();
    fixture.detectChanges(); await fixture.whenStable();
    const apply = overlay.querySelector<HTMLButtonElement>('[data-keep-top-controls] button.mat-mdc-unelevated-button')!;
    expect(apply).not.toBeNull();
    apply.click(); await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable();
    expect(mockStore.selectBottomPercent).toHaveBeenCalledTimes(1);
    expect(review.getAttribute('aria-expanded')).toBe('true');
    expect(overlay.querySelector<HTMLDetailsElement>('[data-keep-top-controls]')?.open).toBe(true);
    apply.click(); await fixture.whenStable(); fixture.detectChanges(); await fixture.whenStable();
    expect(mockStore.selectBottomPercent).toHaveBeenCalledTimes(2);
    expect(review.getAttribute('aria-expanded')).toBe('false');
    expect(overlay.querySelector('[role="dialog"]')).toBeNull();
    expect(overlay.querySelector('[data-keep-top-controls]')).toBeNull();
    expect(document.activeElement).toBe(root.querySelector('[data-mobile-select]'));
    expect(mockStore.selectedPaths()).toEqual(new Set(['/a.jpg']));
    fixture.destroy(); root.remove();
  });

  it('does not close a newer panel or retain stale focus work after Keep top is dismissed while pending', async () => {
    mockAuth['isEdition'] = vi.fn(() => true);
    mockStore.total.set(4);
    let finish!: (result: { paths: string[]; cut: number; truncated: boolean }) => void;
    mockStore.selectBottomPercent = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const fixture = TestBed.createComponent(GalleryComponent);
    document.body.appendChild(fixture.nativeElement); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const review = root.querySelector<HTMLButtonElement>('[data-collection-review] button')!;
    const display = root.querySelector<HTMLButtonElement>('[data-collection-options] button')!;
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    review.click(); fixture.detectChanges();
    overlay.querySelector<HTMLElement>('[data-keep-top-controls] summary')!.click(); fixture.detectChanges();
    overlay.querySelector<HTMLButtonElement>('[data-keep-top-controls] button.mat-mdc-unelevated-button')!.click();
    expect(mockStore.selectBottomPercent).toHaveBeenCalledOnce();
    overlay.querySelector<HTMLDetailsElement>('[data-keep-top-controls]')!.open = false;
    const reviewOwner = fixture.debugElement.query(By.css('[data-collection-review]')).componentInstance as ControlPopoverComponent;
    reviewOwner.open.set(false); fixture.detectChanges();
    display.focus(); display.click(); fixture.detectChanges();
    finish({ paths: ['/a.jpg'], cut: 1, truncated: false }); await fixture.whenStable(); fixture.detectChanges();
    expect(display.getAttribute('aria-expanded')).toBe('true');
    overlay.querySelector<HTMLElement>('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); fixture.detectChanges();
    review.focus(); review.click(); fixture.detectChanges();
    overlay.querySelector<HTMLElement>('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); fixture.detectChanges();
    expect(document.activeElement).toBe(review);
    fixture.destroy(); root.remove();
  });

  it('closes Display on Escape and navigation at either width', () => {
    const fixture = TestBed.createComponent(GalleryComponent);
    const desktop = signal(false);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: desktop });
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const trigger = root.querySelector<HTMLButtonElement>('[data-collection-options] button')!;
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    for (const wide of [false, true]) {
      desktop.set(wide); fixture.detectChanges(); trigger.click(); fixture.detectChanges();
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      overlay.querySelector('button')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      fixture.detectChanges();
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
      expect(overlay.querySelector('[role="dialog"]')).toBeNull();
    }
    trigger.click(); fixture.detectChanges();
    (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(90, '/photo'));
    fixture.detectChanges();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fixture.destroy();
  });

  it('keeps Review open while its filters rewrite the query string', () => {
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const trigger = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-collection-review] button')!;
    const events = TestBed.inject(Router).events as Subject<RouterEvent>;
    expect(TestBed.inject(Router).url.split('?')[0]).toBe('/');
    trigger.click(); fixture.detectChanges();
    events.next(new NavigationStart(91, '/?favorites_only=true')); fixture.detectChanges();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    events.next(new NavigationStart(92, '/albums')); fixture.detectChanges();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fixture.destroy();
  });

  it('switches layout in Display without changing filters or batch selection', () => {
    mockStore.selectedPaths.set(new Set(['/selected.jpg']));
    const filters = mockStore.filters();
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    fixture.nativeElement.querySelector('[data-collection-options] button').click(); fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const grid = overlay.querySelector<HTMLButtonElement>('[data-gallery-layout="grid"]')!;
    const mosaic = overlay.querySelector<HTMLButtonElement>('[data-gallery-layout="mosaic"]')!;
    expect(mosaic.getAttribute('aria-pressed')).toBe('true');
    grid.click(); fixture.detectChanges();
    expect(mockStore.setGalleryMode).toHaveBeenCalledWith('grid');
    expect(grid.getAttribute('aria-pressed')).toBe('true');
    expect(mosaic.getAttribute('aria-pressed')).toBe('false');
    expect(mockStore.filters()).toBe(filters);
    expect([...mockStore.selectedPaths()]).toEqual(['/selected.jpg']);
    fixture.destroy();
  });

  it('offers explicit mobile Select and Cancel without changing the collection or writing metadata', () => {
    mockAuth['isEdition'] = vi.fn(() => false);
    mockStore.galleryMode.set('grid');
    mockStore.photos.set([makePhoto({ path: '/a.jpg' }), makePhoto({ path: '/b.jpg' })]);
    mockStore.clearSelection.mockImplementation(() => {
      mockStore.selectedPaths.set(new Set());
      mockStore.selectionCount.set(0);
    });
    const fixture = TestBed.createComponent(GalleryComponent);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(false) });
    Object.defineProperty(fixture.debugElement.injector.get(MatDialog), 'openDialogs', { value: [] });
    fixture.componentInstance['containerWidth'].set(375);
    mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tooltip_mode: 'click' }));
    fixture.componentInstance['tooltipPhoto'].set(mockStore.photos()[0]);
    fixture.detectChanges();
    const query = mockStore.filters();
    expect(fixture.componentInstance.tooltipDisabled()).toBe(false);
    const button = fixture.nativeElement.querySelector('[data-mobile-select]') as HTMLButtonElement;
    expect(button.textContent).toContain(I18N.gallery.selection.select);
    button.click();
    fixture.detectChanges();
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.getAttribute('aria-label')).toContain(I18N.ui.buttons.cancel);
    expect(button.textContent).toContain(I18N.gallery.selection.count);
    expect(fixture.componentInstance['tooltipPhoto']()).toBeNull();
    expect(fixture.componentInstance.tooltipDisabled()).toBe(true);
    expect(fixture.nativeElement.querySelectorAll('[data-selection-affordance]')).toHaveLength(2);
    expect(fixture.debugElement.queryAll(By.directive(PhotoCardComponent))
      .every(card => card.componentInstance.tooltipMode() === 'off')).toBe(true);
    expect(mockStore.selectAll).not.toHaveBeenCalled();
    expect(mockStore.selectedPaths().size).toBe(0);
    mockStore.selectedPaths.set(new Set(['/a.jpg']));
    mockStore.selectionCount.set(1);
    fixture.detectChanges();
    button.click();
    fixture.detectChanges();
    expect(mockStore.selectedPaths().size).toBe(0);
    expect(button.getAttribute('aria-pressed')).toBe('false');
    expect(fixture.nativeElement.querySelector('[data-selection-affordance]')).toBeNull();
    expect(mockStore.filters()).toBe(query);
    expect(fixture.componentInstance.tooltipDisabled()).toBe(false);
    expect(mockApi.post).not.toHaveBeenCalled();
    fixture.destroy();
  });

  it('disables card tooltips on a narrow viewport while photos are selected, even without the Select affordance', () => {
    mockStore.selectedPaths.set(new Set(['/a.jpg']));
    mockStore.selectionCount.set(1);
    mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tooltip_mode: 'click' }));
    const fixture = TestBed.createComponent(GalleryComponent);
    Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(false) });
    fixture.detectChanges();
    expect(fixture.componentInstance['selectionAffordance']()).toBe(false);
    expect(fixture.componentInstance.tooltipDisabled()).toBe(true);
    expect(fixture.componentInstance['cardTooltipMode']()).toBe('off');
    fixture.destroy();
  });

  it('drops the Select affordance when a view change clears the selection', () => {
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    fixture.componentInstance['selectionAffordance'].set(true);
    mockStore.viewChangeClears.update((n: number) => n + 1);
    fixture.detectChanges();
    expect(fixture.componentInstance['selectionAffordance']()).toBe(false);
    fixture.destroy();
  });

  it('clears a parked tooltip when the docked-rail breakpoint flips panel mode', () => {
    mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tooltip_mode: 'panel' }));
    const fixture = TestBed.createComponent(GalleryComponent);
    const wide = signal(false);
    Object.defineProperty(fixture.componentInstance['railWide'], 'isDesktop', { value: wide, configurable: true });
    fixture.detectChanges();
    expect(fixture.componentInstance.panelMode()).toBe(false);
    fixture.componentInstance['tooltipPhoto'].set({ path: '/a.jpg' } as never);
    wide.set(true);
    fixture.detectChanges();
    expect(fixture.componentInstance.panelMode()).toBe(true);
    expect(fixture.componentInstance['tooltipPhoto']()).toBeNull();
    fixture.destroy();
  });

  it('does not let a parked mobile Select control clear a later selection', () => {
    mockStore.selectedPaths.set(new Set(['/later.jpg']));
    mockStore.selectionCount.set(1);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    (fixture.componentInstance as any).parked = true;
    fixture.nativeElement.querySelector('[data-mobile-select]').click();
    expect(mockStore.clearSelection).not.toHaveBeenCalled();
    expect([...mockStore.selectedPaths()]).toEqual(['/later.jpg']);
    fixture.destroy();
  });

  it('opens a same-session gallery snapshot with its owner nonce', () => {
    const photo = makePhoto({ path: '/alice/portrait.jpg' });
    mockStore.photos.set([photo]);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    component['downloadPhoto'](photo);
    expect(navigate).toHaveBeenCalledWith(['/photo'], {
      queryParams: { path: photo.path }, state: { photo, photoSession: privateImageSessionKey() },
    });
  });

  it('keeps the original owner on a cached gallery row after credentials change', () => {
    const owner = privateImageSessionKey();
    const photo = makePhoto({ path: '/alice/portrait.jpg', filename: 'Alice private portrait.jpg' });
    mockStore.photos.set([photo]);
    resetPrivateImageSession();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    component['downloadPhoto'](mockStore.photos()[0]);
    expect(owner).not.toBe(privateImageSessionKey());
    expect(navigate).toHaveBeenCalledWith(['/photo'], {
      queryParams: { path: photo.path }, state: { photo, photoSession: owner },
    });
  });

  it('renders the translated reason a similar search cannot run instead of a silent empty gallery', () => {
    mockStore.loadError.set(true);
    mockStore.loadErrorKey.set(I18N.similar.no_visual_features);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const alerts = fixture.nativeElement.querySelectorAll('[role="alert"]');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain(I18N.similar.no_visual_features);
    expect(alerts[0].textContent).not.toContain(I18N.gallery.load_error.message);
    fixture.destroy();
  });

  it('falls back to the generic load-error message when the server gave no reason', () => {
    mockStore.loadError.set(true);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain(I18N.gallery.load_error.message);
    fixture.destroy();
  });

  // Shared by every cursor describe below. The component is built without a
  // fixture, so each of these stands in for something the template would
  // otherwise wire up, invoked straight on the instance.
  function activeIndex(): number {
    return (component as unknown as { activeIndex(): number }).activeIndex();
  }

  function hasActivePhoto(): boolean {
    return (component as unknown as { hasActivePhoto(): boolean }).hasActivePhoto();
  }

  function click(photo: { path: string }, index: number): void {
    (component as unknown as {
      toggleSelection(p: unknown, e: MouseEvent | undefined, i: number): void;
    }).toggleSelection(photo, undefined, index);
  }

  function press(key: string): void {
    const ev = new KeyboardEvent('keydown', { key });
    Object.defineProperty(ev, 'target', { value: null, configurable: true });
    (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
  }

  describe('ScoreClassPipe', () => {
    let pipe: ScoreClassPipe;

    beforeEach(() => {
      pipe = new ScoreClassPipe();
    });

    it('should return green class for score >= 8 (no config)', () => {
      expect(pipe.transform(8, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(9.5, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(10, null)).toBe('bg-green-600 text-white');
    });

    it('should return yellow class for score >= 6 and < 8 (no config)', () => {
      expect(pipe.transform(6, null)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(7.9, null)).toBe('bg-yellow-600 text-white');
    });

    it('should return orange class for score >= 4 and < 6 (no config)', () => {
      expect(pipe.transform(4, null)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(5.9, null)).toBe('bg-orange-600 text-white');
    });

    it('should return red class for score < 4 (no config)', () => {
      expect(pipe.transform(3.9, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(0, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(1, null)).toBe('bg-red-600 text-white');
    });

    it('should use config thresholds when provided', () => {
      const config = { quality_thresholds: { excellent: 9, great: 7, good: 5, best: 10 } };
      expect(pipe.transform(9, config)).toBe('bg-green-600 text-white');
      expect(pipe.transform(7, config)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(5, config)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(4, config)).toBe('bg-red-600 text-white');
    });
  });

  describe('keyboard rate-and-advance (onGridKeydown)', () => {
    function keyEvent(key: string, target: Partial<HTMLElement> | null = null): KeyboardEvent {
      const ev = new KeyboardEvent('keydown', { key });
      Object.defineProperty(ev, 'target', { value: target, configurable: true });
      return ev;
    }

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(0);
    });

    function fire(ev: KeyboardEvent) {
      (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
    }

    it('does not advance before an unsuccessful rating settles', async () => {
      mockStore.setRating.mockResolvedValue(false);
      fire(keyEvent('3'));
      expect(activeIndex()).toBe(0);
      await Promise.resolve();
      expect(activeIndex()).toBe(0);
    });

    it('sets the star rating and advances on digit keys only after accepted opt-in', async () => {
      TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
      mockStore.setRating.mockResolvedValue(true);
      fire(keyEvent('3'));
      expect(activeIndex()).toBe(0);
      await Promise.resolve();
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 3);
      expect(activeIndex()).toBe(1);
    });

    it('saves a rating during a page append without advancing while loading', async () => {
      TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
      mockStore.loading.set(true); mockStore.isPageAppending.mockReturnValue(true);
      mockStore.setRating.mockResolvedValue(true);
      fire(keyEvent('3')); await Promise.resolve();
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 3);
      expect(activeIndex()).toBe(0);
    });

    it('rejects and advances on X only after accepted opt-in', async () => {
      TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
      mockStore.toggleRejected.mockResolvedValue(true);
      fire(keyEvent('x'));
      await Promise.resolve();
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(1);
    });

    it('keeps and advances on K after a successful decision', async () => {
      TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
      const keep = vi.spyOn(component.selectionActions, 'reviewSingle').mockResolvedValue({ snapshot: new Map(), targeted: 1, count: 1 });
      fire(keyEvent('k')); await Promise.resolve();
      expect(keep).toHaveBeenCalledWith('/a.jpg', 'kept');
      expect(activeIndex()).toBe(1);
    });

    it('keeps the current photo after a successful rating by default', async () => {
      mockStore.setRating.mockResolvedValue(true);
      fire(keyEvent('4'));
      await Promise.resolve();
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 4);
      expect(activeIndex()).toBe(0);
    });

    it.each(['cursor', 'policy', 'navigation', 'account'] as const)('does not steal focus after %s changes while saving', async ending => {
      const preference = TestBed.inject(GalleryReviewNavigationService);
      preference.setEnabled(true);
      const navigation = new Subject<RouterEvent>();
      if (ending === 'navigation') vi.spyOn(TestBed.inject(Router), 'events', 'get').mockReturnValue(navigation);
      let accept!: (value: boolean) => void;
      mockStore.setRating.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
      fire(keyEvent('4'));
      fire(keyEvent('5'));
      expect(mockStore.setRating).toHaveBeenCalledTimes(1);
      if (ending === 'cursor') fire(keyEvent('End'));
      if (ending === 'policy') { preference.setEnabled(false); preference.setEnabled(true); }
      if (ending === 'navigation') navigation.next(new NavigationStart(99, '/photo/other'));
      if (ending === 'account') (mockAuth['status'] as { set(value: unknown): void }).set({ user_id: 'other' });
      accept(true);
      await Promise.resolve();
      expect(activeIndex()).toBe(ending === 'cursor' ? 2 : 0);
    });

    it('keeps the rated photo after a successful rebuild reorders the collection', async () => {
      let accept!: (value: boolean) => void;
      mockStore.setRating.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
      (component as unknown as { setCursor(index: number): void }).setCursor(0);
      fire(keyEvent('4'));
      mockStore.photos.set([{ path: '/b.jpg' }, { path: '/a.jpg' }, { path: '/c.jpg' }]);
      TestBed.tick();
      accept(true); await Promise.resolve();
      expect(activeIndex()).toBe(1);
      expect(mockStore.focusedPath()).toBe('/a.jpg');
    });

    it.each(['control', 'meta', 'alt', 'composition', 'parked', 'navigation', 'slideshow', 'loading', 'missing-photo'] as const)('does not write a rating during %s', state => {
      const event = new KeyboardEvent('keydown', {
        key: '3', cancelable: true, ctrlKey: state === 'control', metaKey: state === 'meta',
        altKey: state === 'alt', isComposing: state === 'composition',
      });
      if (state === 'parked') outletMock.detachEvents.next(component);
      if (state === 'navigation') vi.spyOn(TestBed.inject(Router), 'currentNavigation').mockReturnValue({ id: 99 } as any);
      if (state === 'slideshow') mockStore.slideshowActive.set(true);
      if (state === 'loading') mockStore.loading.set(true);
      const handler = component as unknown as { handleRatingKey(event: KeyboardEvent, photos: Photo[], index: number): void };
      handler.handleRatingKey(event, mockStore.photos(), state === 'missing-photo' ? 99 : 0);
      expect(mockStore.setRating).not.toHaveBeenCalled();
      expect(activeIndex()).toBe(0);
      expect(event.defaultPrevented).toBe(state === 'loading');
    });

    it('ignores repeated review keys', () => {
      const event = new KeyboardEvent('keydown', { key: '3', repeat: true });
      fire(event);
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    describe('X on a card inside a selection', () => {
      function select(paths: string[]) {
        mockStore.selectedPaths.set(new Set(paths));
        mockStore.selectionCount.set(paths.length);
      }

      it('rejects every selected photo, not just the focused one', async () => {
        select(['/a.jpg', '/c.jpg']);
        fire(keyEvent('x'));
        await Promise.resolve();
        expect(mockStore.batchReject).toHaveBeenCalledWith(['/a.jpg', '/c.jpg']);
        expect(mockStore.toggleRejected).not.toHaveBeenCalled();
        expect(activeIndex()).toBe(0);
      });

      it('rejects only the focused photo when it is outside the selection', () => {
        select(['/b.jpg', '/c.jpg']);
        fire(keyEvent('x'));
        expect(mockStore.batchReject).not.toHaveBeenCalled();
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      });

      it('keeps the single-photo toggle when the selection is just the focused photo', () => {
        select(['/a.jpg']);
        fire(keyEvent('x'));
        expect(mockStore.batchReject).not.toHaveBeenCalled();
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      });
    });

    it('toggles favorite WITHOUT advancing on F', () => {
      fire(keyEvent('f'));
      expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(0);
    });

    it('ignores rating keys while typing in an input', () => {
      fire(keyEvent('1', { tagName: 'INPUT' } as HTMLElement));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys for non-edition users', () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => false);
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys when the feature flag is off', () => {
      mockStore.config.set({ features: { show_rating_controls: false } });
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    describe('remapped keys', () => {
      const keymap = () => TestBed.inject(KeyboardMappingService);
      afterEach(() => {
        keymap().resetAll();
        localStorage.removeItem(KEYMAP_STORAGE_KEY);
      });

      it('rejects with the user-mapped key instead of X', async () => {
        TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
        mockStore.toggleRejected.mockResolvedValue(true);
        keymap().setKey('reject', 'r');
        fire(keyEvent('r'));
        await Promise.resolve();
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
        expect(activeIndex()).toBe(1);
      });

      it('retires the default key once it is remapped away', () => {
        keymap().setKey('reject', 'r');
        fire(keyEvent('x'));
        expect(mockStore.toggleRejected).not.toHaveBeenCalled();
      });

      it('keeps 0 as a reject alias even after X is remapped', () => {
        keymap().setKey('reject', 'r');
        fire(keyEvent('0'));
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      });

      it('toggles favorite with the user-mapped key, still without advancing', () => {
        keymap().setKey('favourite', 'z');
        fire(keyEvent('z'));
        expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/a.jpg');
        expect(activeIndex()).toBe(0);
        mockStore.toggleFavorite.mockClear();
        fire(keyEvent('f'));
        expect(mockStore.toggleFavorite).not.toHaveBeenCalled();
      });

      it('keeps with the user-mapped key', () => {
        keymap().setKey('keep', 'j');
        const reviewSingle = vi.spyOn(
          component.selectionActions,
          'reviewSingle',
        ).mockResolvedValue(null);
        fire(keyEvent('j'));
        expect(reviewSingle).toHaveBeenCalledWith('/a.jpg', 'kept');
        reviewSingle.mockClear();
        fire(keyEvent('k'));
        expect(reviewSingle).not.toHaveBeenCalled();
      });
    });
  });

  describe('the current photo', () => {
    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
    });

    describe('the focused-photo mirror read by ui_get_context', () => {
      const setCursor = (index: number): void =>
        (component as unknown as { setCursor(i: number): void }).setCursor(index);
      let hasFocus: ReturnType<typeof vi.spyOn>;
      beforeEach(() => {
        hasFocus = vi.spyOn(document, 'hasFocus').mockReturnValue(true);
      });
      afterEach(() => hasFocus.mockRestore());

      it('follows the keyboard cursor', () => {
        click({ path: '/a.jpg' }, 0);
        press('ArrowRight');
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('clears on setCursor(-1) while the window has focus', () => {
        click({ path: '/b.jpg' }, 1);
        setCursor(-1);
        expect(mockStore.focusedPath()).toBeNull();
      });

      it('clears when the panel is released', () => {
        click({ path: '/b.jpg' }, 1);
        (component as unknown as { releasePanel(): void }).releasePanel();
        expect(mockStore.focusedPath()).toBeNull();
      });

      it('survives the window losing focus, although the cursor itself goes', () => {
        click({ path: '/b.jpg' }, 1);
        hasFocus.mockReturnValue(false);
        (component as unknown as { onGridFocusOut(e: FocusEvent): void })
          .onGridFocusOut({ relatedTarget: null } as unknown as FocusEvent);
        expect(activeIndex()).toBe(-1);
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('is not touched by hover', () => {
        click({ path: '/b.jpg' }, 1);
        (component as unknown as { tooltipPhoto: { set(p: unknown): void } }).tooltipPhoto.set({ path: '/c.jpg' });
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('clears once its photo leaves the list, even with the cursor already dropped', () => {
        click({ path: '/b.jpg' }, 1);
        hasFocus.mockReturnValue(false);
        (component as unknown as { onGridFocusOut(e: FocusEvent): void })
          .onGridFocusOut({ relatedTarget: null } as unknown as FocusEvent);
        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/c.jpg' }]);
        TestBed.tick();
        expect(mockStore.focusedPath()).toBeNull();
      });
    });

    it('marks nothing before the cursor has ever moved, so nothing is dimmed at rest', () => {
      expect(activeIndex()).toBe(-1);
      expect(hasActivePhoto()).toBe(false);
    });

    it('moves onto the photo the pointer just clicked', () => {
      click({ path: '/c.jpg' }, 2);
      expect(activeIndex()).toBe(2);
      expect(hasActivePhoto()).toBe(true);
    });

    it('still hands the click to the store', () => {
      const photo = { path: '/b.jpg' };
      click(photo, 1);
      expect(mockStore.toggleSelection).toHaveBeenCalledWith(photo, undefined);
    });

    it('rates the photo that was clicked, not the one the arrow keys were left on', () => {
      // The defect: the pointer never moved the cursor, so a rating typed after
      // a click landed on whatever the keyboard had been on. Silently.
      press('ArrowRight');
      expect(activeIndex()).toBe(1);
      click({ path: '/c.jpg' }, 2);
      press('3');
      expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 3);
    });

    it('still moves with the arrow keys once a click has placed it', () => {
      click({ path: '/a.jpg' }, 0);
      press('ArrowRight');
      expect(activeIndex()).toBe(1);
      press('ArrowLeft');
      expect(activeIndex()).toBe(0);
      press('End');
      expect(activeIndex()).toBe(2);
    });

    it('reports no current photo when a shorter result set leaves the cursor past the end', () => {
      // Otherwise the grid would render every card dimmed with none marked.
      click({ path: '/c.jpg' }, 2);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      expect(hasActivePhoto()).toBe(false);
    });

    describe('follows the photo, not the slot it was in', () => {
      // A bounds check only catches the result set getting shorter. One of the
      // same length or longer keeps the index legal, so the marker reframes
      // whatever photo has moved into that slot -- and the next rating keystroke
      // lands there.
      it('re-finds the marked photo when the results are reordered', () => {
        click({ path: '/c.jpg' }, 2);

        mockStore.photos.set([{ path: '/c.jpg' }, { path: '/a.jpg' }, { path: '/b.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(0);
        press('3');
        expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 3);
      });

      it('drops the cursor when the marked photo is gone but the count is not', () => {
        click({ path: '/c.jpg' }, 2);

        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/d.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(-1);
        expect(hasActivePhoto()).toBe(false);
      });

      it('leaves the cursor alone when the photo has not moved', () => {
        click({ path: '/b.jpg' }, 1);

        mockStore.photos.set([
          { path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }, { path: '/d.jpg' },
        ]);
        TestBed.tick();

        expect(activeIndex()).toBe(1);
      });

      it('does nothing at all before the cursor has been placed', () => {
        mockStore.photos.set([{ path: '/x.jpg' }, { path: '/y.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(-1);
      });

      // The three sites that move the cursor have to record the photo as well
      // as the index; a missed one leaves the marker following the slot again.
      it('follows a cursor the arrow keys placed', () => {
        press('ArrowRight');
        expect(activeIndex()).toBe(1);

        mockStore.photos.set([{ path: '/c.jpg' }, { path: '/a.jpg' }, { path: '/b.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(2);
      });

      it('follows a cursor the rate-and-advance keys left behind', async () => {
        TestBed.inject(GalleryReviewNavigationService).setEnabled(true);
        mockStore.setRating.mockResolvedValue(true);
        click({ path: '/a.jpg' }, 0);
        press('3');
        await Promise.resolve();
        expect(activeIndex()).toBe(1);

        mockStore.photos.set([{ path: '/b.jpg' }, { path: '/a.jpg' }, { path: '/c.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(0);
      });
    });
  });

  describe('focus follows the current photo', () => {
    let grid: HTMLElement;
    let barRoot: HTMLElement;
    let bar: HTMLButtonElement;

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);

      // The component is built without a fixture, so the grid its template
      // would render is stood up by hand: focusCard looks a card up by its
      // data-pidx and focuses the first [tabindex] inside it, and the key
      // handler is bound on the role="grid" ancestor.
      grid = document.createElement('div');
      grid.setAttribute('role', 'grid');
      grid.tabIndex = 0;
      for (const index of [0, 1, 2]) {
        const card = document.createElement('div');
        card.setAttribute('data-pidx', String(index));
        const tile = document.createElement('div');
        tile.tabIndex = 0;
        // jsdom lays nothing out and so implements no scrolling, but focusCard
        // really does make the call and it has to land somewhere. Both ends of
        // the card are stubbed because which one is scrolled is the point: the
        // tile takes focus, the card -- which is where scroll-margin lives --
        // is what gets scrolled.
        card.scrollIntoView = vi.fn();
        tile.scrollIntoView = vi.fn();
        card.appendChild(tile);
        grid.appendChild(card);
      }
      document.body.appendChild(grid);

      // Stands in for the action bar's Clear button: outside the grid, and
      // about to be unmounted by the very click that put focus on it. The
      // wrapper carries the marker the grid's focusout handler looks for.
      barRoot = document.createElement('div');
      barRoot.setAttribute('data-selection-bar', '');
      bar = document.createElement('button');
      barRoot.appendChild(bar);
      document.body.appendChild(barRoot);
    });

    afterEach(() => {
      grid.remove();
      barRoot.remove();
    });

    function cardAt(index: number): HTMLElement {
      return grid.querySelector(`[data-pidx="${index}"]`) as HTMLElement;
    }

    function tileAt(index: number): HTMLElement {
      return grid.querySelector(`[data-pidx="${index}"] [tabindex]`) as HTMLElement;
    }

    function clear(): void {
      (component as unknown as { clearSelection(): void }).clearSelection();
    }

    function focusOut(next: HTMLElement | null): void {
      (component as unknown as { onGridFocusOut(e: FocusEvent): void })
        .onGridFocusOut({ relatedTarget: next } as unknown as FocusEvent);
    }

    it('puts the cursor and the focus on the same card when a photo is clicked', () => {
      click({ path: '/c.jpg' }, 2);
      expect(activeIndex()).toBe(2);
      expect(document.activeElement).toBe(tileAt(2));
      // The card, not the tile: scroll-margin does not inherit, and the
      // clearance that lifts the photo out from under the action bar is
      // declared on the card host. Scrolling the tile asks an element that
      // carries none, so the clearance is silently dropped.
      expect(cardAt(2).scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
      expect(tileAt(2).scrollIntoView).not.toHaveBeenCalled();
    });

    it('moves the keyboard cursor with one explicit nearest-edge scroll instead of a browser focus scroll first', () => {
      const focus = vi.spyOn(tileAt(2), 'focus');
      click({ path: '/c.jpg' }, 2);
      expect(document.activeElement).toBe(tileAt(2));
      expect(focus).toHaveBeenCalledExactlyOnceWith({ preventScroll: true });
      expect(cardAt(2).scrollIntoView).toHaveBeenCalledExactlyOnceWith({ block: 'nearest' });
    });

    it('hands focus back to the marked photo when the selection is cleared', () => {
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      expect(document.activeElement).toBe(bar);

      clear();

      expect(document.activeElement).toBe(tileAt(1));
    });

    it('leaves focus somewhere the grid key handler still receives events', () => {
      // The invariant as the user meets it: a marker is drawn, so the arrow
      // keys have to work. onGridKeydown is bound on the grid, which makes that
      // true only while focus is inside one -- and <body> is not.
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      clear();

      const seen: string[] = [];
      grid.addEventListener('keydown', event => seen.push((event as KeyboardEvent).key));
      (document.activeElement as HTMLElement)
        .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));

      expect(seen).toEqual(['ArrowRight']);
    });

    it('keeps the marker and the keystroke target agreeing after a clear', () => {
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      clear();

      expect(activeIndex()).toBe(1);
      expect(document.activeElement).toBe(tileAt(1));
      press('3');
      expect(mockStore.setRating).toHaveBeenCalledWith('/b.jpg', 3);
    });

    it('brings focus back from a batch action that empties the selection too', async () => {
      // The Clear button is only the shortest way in. Every batch action ends
      // the same way, from a control on the same bar.
      click({ path: '/b.jpg' }, 1);
      bar.focus();

      await component.selectionActions.batchFavorite();

      expect(mockStore.clearSelection).toHaveBeenCalled();
      expect(document.activeElement).toBe(tileAt(1));
    });

    it('does not re-focus or re-scroll for an Escape that came from the grid', () => {
      click({ path: '/b.jpg' }, 1);
      mockStore.selectionCount.set(1);
      (cardAt(1).scrollIntoView as unknown as Mock).mockClear();

      press('Escape');

      expect(mockStore.clearSelection).toHaveBeenCalled();
      expect(document.activeElement).toBe(tileAt(1));
      expect(cardAt(1).scrollIntoView).not.toHaveBeenCalled();
    });

    it('does not chase a cursor a narrower filter has left pointing past the end', () => {
      // Nothing is marked in that state, so there is no promise to keep, and
      // the card still standing at that index until the grid re-renders is not
      // the photo the cursor means.
      click({ path: '/c.jpg' }, 2);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      bar.focus();

      clear();

      expect(document.activeElement).toBe(bar);
    });

    it('hands focus back without moving the viewport', () => {
      // The card is still exactly where the user left it, and the action bar
      // unmounting is not a reason to scroll the gallery under them.
      click({ path: '/b.jpg' }, 1);
      (cardAt(1).scrollIntoView as unknown as Mock).mockClear();
      bar.focus();

      clear();

      expect(document.activeElement).toBe(tileAt(1));
      expect(cardAt(1).scrollIntoView).not.toHaveBeenCalled();
    });

    describe('the cursor is dropped when focus leaves the grid', () => {
      // Without this, one mouse click dims the gallery for the rest of the
      // session: the marker fades every other card, and a mouse-only user
      // never puts focus back into a grid to move it off.
      it('resets when focus moves to something outside the grid', () => {
        const sidebar = document.createElement('input');
        document.body.appendChild(sidebar);
        click({ path: '/b.jpg' }, 1);

        focusOut(sidebar);

        expect(activeIndex()).toBe(-1);
        expect(hasActivePhoto()).toBe(false);
        sidebar.remove();
      });

      it('resets when focus falls to the page rather than to an element', () => {
        click({ path: '/b.jpg' }, 1);

        focusOut(null);

        expect(activeIndex()).toBe(-1);
      });

      it('does not reset while the cursor is only moving between cards', () => {
        click({ path: '/a.jpg' }, 0);

        focusOut(tileAt(2));

        expect(activeIndex()).toBe(0);
      });

      it('does not reset for the action bar, which still has to hand focus back', () => {
        click({ path: '/b.jpg' }, 1);

        focusOut(bar);
        expect(activeIndex()).toBe(1);

        clear();
        expect(document.activeElement).toBe(tileAt(1));
      });
    });
  });

  // Every other spec in this file hand-builds the grid, so the three template
  // expressions the marker rides on -- `row.startIndex + i` in the windowed and
  // mosaic branches, a bare `i` in the plain grid -- are never rendered.
  // Dropping `row.startIndex +` from one of them would put the marker on the
  // wrong photo with the whole suite green. These render the real template and
  // identify cards by their position in the grid, never by the data-pidx the
  // same expression writes.
  describe('the marker lands on the card that was clicked (rendered)', () => {
    const photos = Array.from({ length: 12 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.nativeElement.remove();
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function render(mode: 'grid' | 'mosaic' | 'list', virtual: boolean): HTMLElement[] {
      mockStore.photos.set(photos);
      mockStore.config.set({ features: { show_rating_controls: true } });
      // The floating tooltip: the docked rail (the default at this width) would
      // render a full details panel these path-only stand-in photos cannot fill.
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      if (mode === 'mosaic' || virtual) {
        // The row-based branches need a desktop-width container that has been
        // measured, and jsdom lays nothing out: widen the media query the way
        // the rail specs do, and feed the width the ResizeObserver would have.
        vi.stubGlobal('matchMedia', (media: string) => ({
          matches: true, media, addEventListener() {}, removeEventListener() {},
        }));
        instance.desktop.setup();
        instance.containerWidth.set(1200);
      }
      fixture.detectChanges();
      // A branch that quietly fell back to the plain grid would satisfy every
      // assertion below without ever rendering the expression under test.
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe(mode);
      expect(fixture.componentInstance.virtualOn()).toBe(virtual);
      const cards = [...fixture.nativeElement.querySelectorAll('app-photo-card')] as HTMLElement[];
      for (const card of cards) card.scrollIntoView = vi.fn();
      // Two rows at least, so the card the specs reach for is never in the first.
      expect(cards.length).toBeGreaterThan(gridColumnCount(1200 - 32, 300, 8, true));
      return cards;
    }

    function clickCard(card: HTMLElement): void {
      (card.querySelector('[role="button"]') as HTMLElement).click();
      fixture!.detectChanges();
    }

    function markedCard(cards: HTMLElement[]): number {
      return cards.findIndex(c => c.querySelector('[aria-current="true"]'));
    }

    for (const [name, mode, virtual] of [
      ['plain grid', 'grid', false],
      ['mosaic', 'mosaic', false],
      ['windowed rows', 'mosaic', true],
      ['plain metadata list', 'list', false],
      ['windowed metadata list', 'list', true],
    ] as const) {
      it(`indexes every card by its place in the results (${name})`, () => {
        const cards = render(mode, virtual);
        expect(cards.map(c => c.getAttribute('data-pidx')))
          .toEqual(cards.map((_, n) => String(n)));
      });

      it(`marks the card that was clicked, not the one at its offset in the row (${name})`, () => {
        const cards = render(mode, virtual);
        const target = cards.length - 2; // past the first row in every branch

        clickCard(cards[target]);

        expect(markedCard(cards)).toBe(target);
      });

      // The handler is unit-tested above; what only a rendered template can say
      // is that all three grid containers are actually bound to it.
      it(`drops the marker when focus leaves the grid (${name})`, () => {
        const cards = render(mode, virtual);
        clickCard(cards[cards.length - 2]);
        expect(markedCard(cards)).toBeGreaterThan(-1);

        (fixture!.nativeElement.querySelector(mode === 'list' ? '[data-photo-collection]' : '[role="grid"]') as HTMLElement)
          .dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
        fixture!.detectChanges();

        expect(markedCard(cards)).toBe(-1);
      });
    }
    it('retains the metadata list cursor during actual focus movement between attached rows', () => {
      const cards = render('list', false);
      document.body.appendChild(fixture!.nativeElement);
      clickCard(cards[0]);
      cards[0].querySelector<HTMLElement>('[role=button]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
      fixture!.detectChanges();
      expect(markedCard(cards)).toBe(1);
      expect(document.activeElement).toBe(cards[1].querySelector('[role=button]'));
    });
    it('matches metadata list width and stacked height to actual rem-scaled collection padding', () => {
      render('list', true);
      const instance = fixture!.componentInstance as unknown as {
        containerWidth: WritableSignal<number>; rootFontSize: WritableSignal<number>;
        desktop: { setup(): void; cleanup(): void };
      };
      instance.desktop.cleanup();
      vi.stubGlobal('matchMedia', (media: string) => ({ matches: false, media, addEventListener() {}, removeEventListener() {} }));
      instance.desktop.setup(); instance.containerWidth.set(320); instance.rootFontSize.set(32);
      fixture!.detectChanges();
      const row = fixture!.componentInstance.rowsModel()[0];
      expect(row.widths).toEqual([288]); expect(row.height).toBe(288);
      const card = fixture!.nativeElement.querySelector('app-photo-card') as HTMLElement;
      expect(card.style.width).toBe('288px'); expect(card.style.height).toBe('288px');
    });
    it('restores a metadata list layout anchor without stealing toolbar focus and yields to new input', () => {
      const cards = render('list', false);
      document.body.appendChild(fixture!.nativeElement);
      clickCard(cards[0]);
      mockStore.initializing.set(false);
      const instance = fixture!.componentInstance as unknown as {
        scrollContent(): { getElementRef(): { nativeElement: HTMLElement }; scrollTo(options: { top: number }): void; measureScrollOffset(side: string): number };
        preserveLayoutAnchor(): void;
      };
      const content = instance.scrollContent(); const viewport = content.getElementRef().nativeElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 359, 400));
      let top = 20;
      vi.spyOn(cards[0], 'getBoundingClientRect').mockImplementation(() => new DOMRect(0, top, 359, 144));
      const scroll = vi.spyOn(content, 'scrollTo').mockImplementation(() => {});
      vi.spyOn(content, 'measureScrollOffset').mockReturnValue(0);
      const toolbar = fixture!.nativeElement.querySelector('[data-collection-header] button') as HTMLButtonElement;
      toolbar.focus();
      const frames: FrameRequestCallback[] = [];
      vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.push(callback); return frames.length; });
      instance.preserveLayoutAnchor(); top = 140;
      while (frames.length) frames.shift()!(0);
      expect(scroll).toHaveBeenCalledExactlyOnceWith({ top: 120 }); expect(document.activeElement).toBe(toolbar);
      scroll.mockClear(); top = 20; instance.preserveLayoutAnchor(); top = 140;
      document.dispatchEvent(new WheelEvent('wheel', { bubbles: true }));
      while (frames.length) frames.shift()!(0);
      expect(scroll).not.toHaveBeenCalled();
    });
  });

  describe('the panel place falls back to the floating tooltip where the rail cannot dock (rendered)', () => {
    const photos = Array.from({ length: 4 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
      tags_list: [], persons: [],
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function renderPanel(): HTMLElement[] {
      mockStore.photos.set(photos);
      // The floating tooltip fetches its own extras once it renders.
      Object.assign(mockApi, { get: vi.fn(() => of({})) });
      mockStore.config.set({ features: { show_rating_controls: true } });
      // The docked rail would render a full details panel these path-only
      // stand-in photos cannot fill; the floating bubble is what is asserted on.
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel', panel_activation: 'both' });
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return [...fixture.nativeElement.querySelectorAll('app-photo-card')] as HTMLElement[];
    }

    const floatingTooltips = (): Element[] =>
      (Array.from(fixture!.nativeElement.querySelectorAll('app-photo-tooltip')) as Element[])
        .filter(el => !el.closest('[data-details-rail]'));

    it('shows the floating bubble when a card is tapped', () => {
      const cards = renderPanel();
      // jsdom's matchMedia is false, so the rail cannot dock: the panel place
      // must come back as the floating bubble instead of rendering nothing.
      const tile = cards[0].querySelector('[role="button"]') as HTMLElement;
      tile.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      fixture!.detectChanges();
      const inst = fixture!.componentInstance as unknown as {
        tooltipPhoto(): unknown; tooltipX(): number;
      };
      expect(inst.tooltipPhoto()).toBeTruthy();
      expect(inst.tooltipX()).toBeGreaterThan(0);
      expect(floatingTooltips().length).toBe(1);
    });

    it('leaves the presentation to the docked rail once the viewport can hold it', () => {
      // A desktop-wide viewport from the first paint, the way production meets it.
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {},
      }));
      renderPanel();
      const wide = fixture!.componentInstance as unknown as {
        railWide: { setup(): void };
        showTooltip(e: unknown, p: unknown): void;
        tooltipPhoto(): unknown;
      };
      wide.railWide.setup();
      fixture!.detectChanges();
      // The event chain into showTooltip is bound identically in all three card
      // loops and pinned by the narrow test; what only this rendered template can
      // say is that the docked rail, not the floating bubble, shows the photo.
      wide.showTooltip({ currentTarget: null } as unknown as MouseEvent, photos[0]);
      fixture!.detectChanges();
      expect(wide.tooltipPhoto()).toBeTruthy();
      const floating = floatingTooltips();
      expect(floating.length).toBe(0); // no floating bubble beside the rail
      expect(fixture!.nativeElement.querySelector('[data-details-rail] app-photo-tooltip')).toBeTruthy(); // rail holds the photo
    });
  });

  describe('ngOnInit()', () => {
    it.each([
      { changedSession: false, setScope: false },
      { changedSession: true, setScope: false },
      { changedSession: true, setScope: true },
    ])('destroy/recreate validates the source session before restoring rows: $changedSession, scoped: $setScope', async ({ changedSession, setScope }) => {
      const alice = makePhoto({ path: '/alice/private.jpg', filename: 'Alice private portrait.jpg' });
      const bob = makePhoto({ path: '/bob/visible.jpg', filename: 'Bob visible portrait.jpg' });
      mockStore.loadPhotos.mockImplementation(async () => { mockStore.photos.set([alice]); });
      const first = TestBed.createComponent(GalleryComponent);
      first.detectChanges();
      await first.whenStable();
      first.detectChanges();
      expect(first.debugElement.queryAll(By.directive(PhotoCardComponent))).toHaveLength(1);
      first.destroy();
      expect(mockStore.viewSnapshot()).toBeTruthy();
      mockStore.loadConfig.mockClear();
      mockStore.loadPhotos.mockClear();
      let releaseConfig!: () => void;
      if (changedSession) {
        resetPrivateImageSession();
        (mockAuth['status'] as WritableSignal<{ user_id: string }>).set({ user_id: 'bob' });
        mockStore.loadConfig.mockImplementation(() => new Promise<boolean>(resolve => { releaseConfig = () => resolve(true); }));
        mockStore.loadPhotos.mockImplementation(async () => { mockStore.photos.set([bob]); });
      }
      if (setScope) history.replaceState({ setScope: { sequence_group_id: '4', sequence_kind: 'bracket' } }, '', location.href);
      const second = TestBed.createComponent(GalleryComponent);
      try {
        second.detectChanges();
        if (changedSession) {
          // A slow configuration load must not leave the previous account's rows clickable.
          expect(mockStore.photos()).toEqual([]);
          expect(second.debugElement.queryAll(By.directive(PhotoCardComponent))).toHaveLength(0);
          expect(mockStore.loadConfig).toHaveBeenCalledOnce();
          releaseConfig();
        }
        await second.whenStable();
        second.detectChanges();
        const cards = second.debugElement.queryAll(By.directive(PhotoCardComponent));
        expect(cards).toHaveLength(1);
        expect((cards[0].componentInstance as PhotoCardComponent).photo().path).toBe(changedSession ? bob.path : alice.path);
        if (changedSession) expect(mockStore.loadPhotos).toHaveBeenCalledOnce();
        else {
          expect(mockStore.loadConfig).not.toHaveBeenCalled();
          expect(mockStore.loadPhotos).not.toHaveBeenCalled();
        }
      } finally {
        releaseConfig?.();
        second.destroy();
        history.replaceState(null, '', location.href);
      }
    });

    it('should call store.loadConfig, loadFilterOptions, loadTypeCounts, and loadPhotos', async () => {
      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadFilterOptions).toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('should call loadConfig before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve(true);
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('should call loadPhotos before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve(true);
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('reloads instead of restoring when the URL carries different query params (issue #70)', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey(), photoSession: privateImageSessionKey() });
      routeMock.snapshot.queryParams = {
        date_from: '2026-01-01', date_to: '2026-01-01', sort: 'date_taken', sort_direction: 'DESC',
      };

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('captures a recent-collection intent before navigation info disappears and refuses the old matching snapshot', async () => {
      const router = TestBed.inject(Router);
      const navigation = vi.spyOn(router, 'currentNavigation').mockReturnValue({
        extras: { info: GALLERY_REVISIT },
      } as unknown as ReturnType<Router['currentNavigation']>);
      const revisit = TestBed.runInInjectionContext(() => new GalleryComponent());
      navigation.mockReturnValue(null);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 640, albumId: null, filterKey: mockStore.filterKey() });

      await revisit.ngOnInit();

      expect(mockStore.viewSnapshot()).toBeNull();
      expect(mockStore.loadConfig).toHaveBeenCalledOnce();
      expect(mockStore.loadPhotos).toHaveBeenCalledOnce();
      expect(mockStore.resumeListingReads).not.toHaveBeenCalled();
    });

    it('restores the previous view when the URL matches the snapshot', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey(), photoSession: privateImageSessionKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.resumeListingReads).toHaveBeenCalledOnce();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('applies the session query on a parameterless `/`, so the nav-icon return keeps filters', async () => {
      routeMock.snapshot.queryParams = {};
      mockStore.readGallerySessionQuery.mockReturnValue({ blinks_only: 'true' });

      await component.ngOnInit();

      // Applied AFTER loadConfig's wholesale filter rebuild -- a navigate-based
      // restore could not work: the ActivatedRoute snapshot never refreshes for
      // same-component param-only navigations.
      expect(mockStore.applySessionQuery).toHaveBeenCalledWith({ blinks_only: 'true' });
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('does not consult the session query when the URL carries its own params', async () => {
      routeMock.snapshot.queryParams = { sort: 'date_taken' };

      await component.ngOnInit();

      expect(mockStore.readGallerySessionQuery).not.toHaveBeenCalled();
      expect(mockStore.applySessionQuery).not.toHaveBeenCalled();
    });

    it('records its own filters in the session query after loadConfig on a plain init', async () => {
      routeMock.snapshot.queryParams = {};
      const order: string[] = [];
      mockStore.loadConfig.mockImplementation(async () => { order.push('loadConfig'); return true; });
      mockStore.saveSessionQuery.mockImplementation(() => { order.push('saveSessionQuery'); });

      await component.ngOnInit();

      expect(order).toEqual(['loadConfig', 'saveSessionQuery']);
    });

    it('does not write the session query on an album route', async () => {
      routeMock.snapshot.paramMap.get = vi.fn((k: string) => (k === 'albumId' ? '7' : null));
      routeMock.snapshot.queryParams = {};

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.saveSessionQuery).not.toHaveBeenCalled();
    });

    it('does not consult the session query on an album route', async () => {
      routeMock.snapshot.paramMap.get = vi.fn((k: string) => (k === 'albumId' ? '7' : null));
      routeMock.snapshot.queryParams = {};

      await component.ngOnInit();

      expect(mockStore.readGallerySessionQuery).not.toHaveBeenCalled();
      expect(mockStore.applySessionQuery).not.toHaveBeenCalled();
    });

    it('should show photos and stop initializing when a filter-option request never resolves', async () => {
      mockStore.loadFilterOptions.mockImplementation(() => new Promise<void>(() => {}));
      mockStore.loadPhotos.mockImplementation(() => {
        mockStore.photos.set([{ path: '/a.jpg' }]);
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(mockStore.loadPhotos).toHaveBeenCalled();
      expect(mockStore.photos()).toHaveLength(1);
      expect(mockStore.initializing()).toBe(false);
    });

    describe('set scope carried from photo-detail navigation state', () => {
      afterEach(() => {
        history.replaceState({}, '', '/');
      });

      it('applies the scope before the first load, then clears it so a reload falls back to the plain gallery', async () => {
        history.replaceState({
          setScope: {
            sequence_group_id: '68', sequence_kind: 'bracket', burst_group_id: '', duplicate_group_id: '',
            hide_brackets: false,
          },
        }, '', '/');

        await component.ngOnInit();

        expect(mockStore.loadConfig).toHaveBeenCalled();
        expect(mockStore.filters()).toMatchObject({
          sequence_group_id: '68', sequence_kind: 'bracket', hide_brackets: false,
        });
        // Cleared immediately: browsers keep history.state for the current
        // entry across a reload, so leaving it would resolve a reload to a
        // possibly different (renumbered) set instead of the plain gallery.
        expect((history.state as Record<string, unknown> | null)?.['setScope']).toBeUndefined();
      });

      it('bypasses the restore-previous-view fast path even when the snapshot matches', async () => {
        // Same setup as 'restores the previous view when the URL matches the
        // snapshot' above, which normally skips loadConfig/loadPhotos entirely
        // -- a scoped "open this set" request must still get a fresh load.
        mockStore.photos.set([{ path: '/a.jpg' }]);
        mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey(), photoSession: privateImageSessionKey() });
        history.replaceState({
          setScope: {
            sequence_group_id: '5', sequence_kind: 'panorama', burst_group_id: '', duplicate_group_id: '',
            hide_panoramas: false,
          },
        }, '', '/');

        await component.ngOnInit();

        expect(mockStore.loadConfig).toHaveBeenCalled();
        expect(mockStore.loadPhotos).toHaveBeenCalled();
        expect(mockStore.filters()).toMatchObject({
          sequence_group_id: '5', sequence_kind: 'panorama', hide_panoramas: false,
        });
      });

      it('preserves unrelated history-state keys when clearing the consumed scope', async () => {
        history.replaceState({
          setScope: {
            sequence_group_id: '1', sequence_kind: '', burst_group_id: '1', duplicate_group_id: '',
            hide_bursts: false,
          },
          unrelated: 'keep-me',
        }, '', '/');

        await component.ngOnInit();

        const state = history.state as Record<string, unknown>;
        expect(state['unrelated']).toBe('keep-me');
        expect(state['setScope']).toBeUndefined();
      });

      it('does not touch filters when there is no set-scope state', async () => {
        history.replaceState({}, '', '/');
        const before = mockStore.filters();

        await component.ngOnInit();

        expect(mockStore.filters()).toBe(before);
      });
    });
  });

  describe('clearSetScope()', () => {
    afterEach(() => {
      localStorage.removeItem(DISPLAY_OPTIONS_KEY);
    });

    it('does nothing when no set scope is active', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS });

      component.clearSetScope();

      expect(mockStore.updateFilters).not.toHaveBeenCalled();
    });

    it('restores the user\'s stored hide_bursts preference instead of hardcoding true', () => {
      localStorage.setItem(DISPLAY_OPTIONS_KEY, JSON.stringify({ hide_bursts: false }));
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '7', hide_bursts: false });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_bursts: false,
      });
    });

    const CLEARED = { sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '' };
    const STASH = { hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true };

    it('puts back what a set-bar Show all lifted, keeping the set\'s own restore', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '161' });
      localStorage.setItem(DISPLAY_OPTIONS_KEY, JSON.stringify({ hide_bursts: true }));
      mockStore.showAllHidden.mockImplementation(() => mockStore.hiddenFiltersStash.set(STASH));
      mockStore.takeTransientRestore.mockReturnValueOnce({ hide_blinks: true, hide_bursts: false, hide_rejected: true });

      component.showWholeSet();
      component.clearSetScope();

      expect(mockStore.showAllHidden).toHaveBeenCalledWith({ persist: false, includeRejected: true });
      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        ...CLEARED, hide_blinks: true, hide_bursts: true, hide_rejected: true,
      });
      expect(mockStore.hiddenFiltersStash()).toBeNull();
    });

    it('restores only what the store reports still lifted, so a manual toggle is not fought', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '161' });
      mockStore.takeTransientRestore.mockReturnValueOnce({ hide_duplicates: true });

      component.clearSetScope();

      const [updates] = mockStore.updateFilters.mock.calls.at(-1)!;
      expect(updates).toEqual({ ...CLEARED, hide_duplicates: true, hide_bursts: true });
      expect(updates).not.toHaveProperty('hide_blinks');
    });

    it('ends the Show all when the set scope goes away by another route', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '161' });
      mockStore.showAllHidden.mockImplementation(() => mockStore.hiddenFiltersStash.set(STASH));
      TestBed.flushEffects();
      component.showWholeSet();
      mockStore.takeTransientRestore.mockReturnValueOnce({ hide_blinks: true, hide_rejected: true });

      mockStore.filters.set({ ...mockStore.filters(), burst_group_id: '' });
      TestBed.flushEffects();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({ hide_blinks: true, hide_rejected: true });
      expect(mockStore.hiddenFiltersStash()).toBeNull();
    });

    it('leaves a gallery-wide Show all alone when the set is cleared', () => {
      const stash = { hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true };
      mockStore.hiddenFiltersStash.set(stash);
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, burst_group_id: '161', hide_bursts: false });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '', hide_bursts: true,
      });
      expect(mockStore.hiddenFiltersStash()).toBe(stash);
      mockStore.hiddenFiltersStash.set(null);
    });

    it('falls back to the config default when nothing is stored in localStorage', () => {
      mockStore.config.set({ defaults: { hide_panoramas: false } });
      mockStore.filters.set({
        ...DEFAULT_FILTERS, sequence_kind: 'panorama', sequence_group_id: '3', hide_panoramas: false,
      });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_panoramas: false,
      });
    });

    it('falls back to true when neither storage nor config supplies a value', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, duplicate_group_id: '9', hide_duplicates: false });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_duplicates: true,
      });
    });
  });

  describe('hidden-photos banner toggle', () => {
    // showAllHidden()/restoreHidden() now live on GalleryStore (see
    // gallery.store.spec.ts) — the component only derives canRestoreHidden
    // from the store's hiddenFiltersStash + filters signals.
    it('offers the restore once a stash exists and every toggle is off', () => {
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(true);
    });

    it.each(['blinks_only', 'duplicates_only', 'show_rejected'] as const)('withdraws the restore while %s is up: that view is not "showing all photos"', key => {
        mockStore.hiddenFiltersStash.set({
          hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
        });
        mockStore.filters.set({ ...DEFAULT_FILTERS, [key]: true });
        expect(component.canRestoreHidden()).toBe(false);
      });

    it('offers no restore before Show all has been used', () => {
      expect(component.canRestoreHidden()).toBe(false);
    });

    it('withdraws the restore once a hide filter is switched back on by hand', () => {
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(false);
    });
  });

  describe('select-all keyboard shortcut', () => {
    // Document-level host bindings register only when the view renders, so
    // each case makes its own fixture and dispatches straight at document.
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function renderWithPhotos(): void {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
    }

    it.each([
      ['control', false], ['meta', true],
    ])('selects all loaded photos on %s+A', (_label, metaKey) => {
      renderWithPhotos();
      const event = new KeyboardEvent('keydown', { key: 'a', metaKey, ctrlKey: !metaKey, cancelable: true });
      const prevented = !document.dispatchEvent(event);
      expect(prevented).toBe(true);
      expect(mockStore.selectAll).toHaveBeenCalled();
    });

    it('leaves the browser default alone while focus is in an input', () => {
      renderWithPhotos();
      const input = document.createElement('input');
      document.body.appendChild(input);
      input.focus();
      try {
        // Bubbling from the input, as a real keypress would: the guard reads
        // the event's target, so the event must originate there.
        const event = new KeyboardEvent('keydown', { key: 'a', metaKey: true, bubbles: true, cancelable: true });
        expect(input.dispatchEvent(event)).toBe(true);
        expect(mockStore.selectAll).not.toHaveBeenCalled();
      } finally {
        input.remove();
      }
    });
  });

  describe('assistant-pinned list', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    it('keeps the pin when the gallery is restored from a /photo round trip', async () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey(), photoSession: privateImageSessionKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.pinnedPaths()).toEqual(['/a.jpg']);
    });

    it('reloads through loadConfig and loadPhotos (which drop the pin) when it cannot restore', async () => {
      mockStore.pinnedPaths.set(['/a.jpg']);

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('renders the chip with the count and its button clears the pin', () => {
      mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg']);
      mockStore.total.set(2);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      expect(html.textContent).toContain(I18N.gallery.pinned.chip_plural);
      expect(html.querySelector('[role="status"]')).toBeTruthy();
      const clear = Array.from(html.querySelectorAll('button')).find(b => b.textContent?.includes(I18N.gallery.pinned.clear));
      expect(clear).toBeTruthy();
      clear?.click();
      expect(mockStore.clearPinned).toHaveBeenCalled();
    });

    function toolbarView(): HTMLElement {
      return fixture!.nativeElement.querySelector('[data-collection-query]');
    }
    const hasSearch = (host: HTMLElement) =>
      !!host.querySelector(`input[type="search"]`);

    it('offers no filter links while pinned (tag chips, person avatars, Find similar) and restores them after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.photos.set([{ path: '/a.jpg', filename: 'a.jpg', image_width: 4000, image_height: 3000 }]);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const cards = () => fixture!.debugElement.queryAll(By.directive(PhotoCardComponent));
      const menu = () => fixture!.debugElement.query(By.directive(GalleryPhotoMenuComponent)).componentInstance as GalleryPhotoMenuComponent;
      const tooltips = () => fixture!.debugElement.queryAll(By.directive(PhotoTooltipComponent));
      expect(cards().length).toBeGreaterThan(0);
      expect(cards().every(c => (c.componentInstance as PhotoCardComponent).filterLinks() === false)).toBe(true);
      expect(menu().findSimilar()).toBe(false);
      expect(tooltips().every(t => (t.componentInstance as PhotoTooltipComponent).personLinks() === false)).toBe(true);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(cards().every(c => (c.componentInstance as PhotoCardComponent).filterLinks() === true)).toBe(true);
      expect(menu().findSimilar()).toBe(true);
      expect(tooltips().every(t => (t.componentInstance as PhotoTooltipComponent).personLinks() === true)).toBe(true);
    });

    it('hides the header Type select and search field while pinned and restores them after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect(hasSearch(toolbarView())).toBe(false);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(hasSearch(toolbarView())).toBe(true);
    });

    it('keeps the filter drawer shut while pinned without touching the persisted flag, and reopens it after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.filterDrawerOpen.set(true);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
      expect(drawer.opened).toBe(false);
      expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
      expect(mockStore.filterDrawerOpen()).toBe(true);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(drawer.opened).toBe(true);
      mockStore.filterDrawerOpen.set(false);
    });

    it('ignores a stale drawer animation event that no longer matches the drawer, so a quick close and reopen cannot ping-pong', async () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.filterDrawerOpen.set(true);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
      expect(drawer.opened).toBe(true);
      mockStore.setFilterDrawerOpen.mockClear();
      // The close animation of an earlier close() finishes after the reopen.
      drawer.openedChange.emit(false);
      await new Promise(resolve => setTimeout(resolve));
      expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
      mockStore.filterDrawerOpen.set(false);
    });

    it('the load-error Retry button reloads without dropping the pin', () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.loadError.set(true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const retry = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'))
        .find(b => b.textContent?.includes(I18N.gallery.load_error.retry));
      expect(retry).toBeTruthy();
      retry?.click();
      expect(mockStore.reloadPhotos).toHaveBeenCalled();
      mockStore.loadError.set(false);
    });

    it('hides the Keep top N% button while a pinned list is shown', () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.total.set(2);
      mockStore.canScopeSelectionToView.set(false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).querySelector(`[aria-label="${I18N.gallery.keep_top.label}"]`)).toBeNull();
      mockStore.canScopeSelectionToView.set(true);
    });

    it('renders the pinned chip with only a Clear button: no review legend, Copy, Apply or Applied menu', () => {
      mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg']);
      mockStore.total.set(2);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const chip = (fixture.nativeElement as HTMLElement).querySelector('[data-pinned-summary][role="status"]')!;
      expect(chip.querySelectorAll('button')).toHaveLength(1);
      expect(chip.querySelector('[data-testid="pinned-review-legend"], [data-testid="copy-for-assistant"], [data-testid="apply-my-marks"], [data-testid="applied-menu"]')).toBeNull();
    });

    it('uses the singular chip text for one photo', () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.total.set(1);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
      expect(text).toContain(I18N.gallery.pinned.chip);
      expect(text).not.toContain(I18N.gallery.pinned.chip_plural);
    });

    it('renders no chip without a pin', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).textContent).not.toContain(I18N.gallery.pinned.chip);
    });
  });

  describe('collapsedSetKinds', () => {
    it('lists nothing when every hide toggle is off', () => {
      mockStore.filters.set({
        ...DEFAULT_FILTERS, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false,
      });
      expect(component.collapsedSetKinds()).toEqual([]);
    });

    it('lists a kind per toggle that is on', () => {
      mockStore.filters.set({
        ...DEFAULT_FILTERS, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      expect(component.collapsedSetKinds()).toEqual(['burst', 'duplicate', 'bracket', 'panorama', 'hdr_panorama']);
    });
  });

  describe('thumbnail-migration banner', () => {
    function rebuild(): GalleryComponent {
      return TestBed.runInInjectionContext(() => new GalleryComponent());
    }

    beforeEach(() => {
      sessionStorage.removeItem(NOTICE_DISMISSALS_KEY);
      component = rebuild();
    });

    afterEach(() => sessionStorage.removeItem(NOTICE_DISMISSALS_KEY));

    it('stays hidden until the server reports rows awaiting regeneration', () => {
      mockStore.config.set({ render_migration: { pending: 0 } });
      expect(component.showRenderMigrationBanner()).toBe(false);
    });

    it('stays hidden on a build whose config carries no migration block', () => {
      mockStore.config.set({ features: {} });
      expect(component.renderMigrationPending()).toBe(0);
      expect(component.showRenderMigrationBanner()).toBe(false);
    });

    it('shows the pending count once the server reports one', () => {
      mockStore.config.set({ render_migration: { pending: 1234 } });
      expect(component.renderMigrationPending()).toBe(1234);
      expect(component.showRenderMigrationBanner()).toBe(true);
    });

    it('closes for this tab, stays closed after a reload, and reopens once the pending count changes', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      component['dismissNotice']('render_migration');

      expect(component.showRenderMigrationBanner()).toBe(false);
      expect(localStorage.getItem('facet_render_migration_dismissed')).toBeNull();
      expect(rebuild().showRenderMigrationBanner()).toBe(false);

      mockStore.config.set({ render_migration: { pending: 11 } });
      expect(component.showRenderMigrationBanner()).toBe(true);
    });
  });

  describe('floating advisory notices', () => {
    function render(): HTMLElement {
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }
    const stack = (html: HTMLElement) => html.querySelector<HTMLElement>('[data-gallery-notices]');
    const button = (html: HTMLElement, label: string) =>
      Array.from(html.querySelectorAll('button')).find(b => b.textContent?.includes(label));

    /** The close button of the one card whose text contains `text`, never a positional pick. */
    const closeFor = (html: HTMLElement, text: string) =>
      Array.from(stack(html)!.children).find(card => card.textContent?.includes(text))!
        .querySelector<HTMLButtonElement>(`button[aria-label="${I18N.ui.buttons.dismiss}"]`)!;

    beforeEach(() => {
      sessionStorage.removeItem(NOTICE_DISMISSALS_KEY);
      mockStore.hiddenSummary.set({ total: 6, blinks: 0, bursts: 4, duplicates: 0, brackets: 2, panoramas: 0 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_bursts: true });
    });

    afterEach(() => sessionStorage.removeItem(NOTICE_DISMISSALS_KEY));

    it('renders the hidden-photos notice in the stack, outside the scrolling content, and Show all acts', () => {
      const html = render();
      const notices = stack(html);
      expect(notices).toBeTruthy();
      expect(notices!.closest('mat-sidenav-content')).toBeNull();
      expect(notices!.querySelector('[role="status"]')?.textContent).toContain(I18N.gallery.hidden_banner.message);
      button(html, I18N.gallery.hidden_banner.show_all)?.click();
      expect(mockStore.showAllHidden).toHaveBeenCalled();
    });

    it('the hidden-photos notice lists only the reasons with a non-zero count', () => {
      const text = stack(render())!.querySelector('[role="status"]')!.textContent!;
      const reasons = I18N.gallery.hidden_banner;
      expect(text).toContain(reasons.reason_bursts);
      expect(text).toContain(reasons.reason_brackets);
      expect(text).not.toContain(reasons.reason_blinks);
      expect(text).not.toContain(reasons.reason_duplicates);
      expect(text).not.toContain(reasons.reason_panoramas);
    });

    it('the set-scope bar says what the hide toggles left out, so its count matches the photo page', () => {
      // A burst of 3 whose blink frame hide_blinks still filters out: the bar must
      // not leave the user to reconcile 2 tiles with "3 photos" on the photo page.
      mockStore.total.set(2);
      mockStore.hiddenSummary.set({ total: 1, blinks: 1, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, burst_group_id: '161' });
      const html = render();
      const bar = Array.from(html.querySelectorAll('mat-sidenav-content > div'))
        .find(el => el.textContent?.includes(I18N.gallery.set_scope.message))!;
      expect(bar.textContent).toContain(I18N.gallery.set_scope.partial);
      Array.from(bar.querySelectorAll('button')).find(b => b.textContent?.includes(I18N.gallery.hidden_banner.show_all))!.click();
      expect(mockStore.showAllHidden).toHaveBeenCalled();
    });

    it('the set-scope bar counts rejected frames, names them, and drops them once hide_rejected is off', () => {
      mockStore.total.set(2);
      mockStore.hiddenSummary.set({ total: 1, blinks: 1, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0, rejected: 1 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_rejected: true, burst_group_id: '161' });
      const html = render();
      const bar = () => Array.from(html.querySelectorAll('mat-sidenav-content > div'))
        .find(el => el.textContent?.includes(I18N.gallery.set_scope.message))!;
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.gallery.hidden_banner.reason_rejected, { n: 1 });
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.gallery.set_scope.partial, expect.objectContaining({ shown: 2, total: 4 }));
      expect(bar().textContent).toContain(I18N.gallery.set_scope.partial);
    });

    it('the set-scope bar offers Show all for rejected frames alone', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0, rejected: 2 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_rejected: true, burst_group_id: '161' });
      const html = render();
      const bar = Array.from(html.querySelectorAll('mat-sidenav-content > div'))
        .find(el => el.textContent?.includes(I18N.gallery.set_scope.message))!;
      expect(Array.from(bar.querySelectorAll('button')).some(b => b.textContent?.includes(I18N.gallery.hidden_banner.show_all))).toBe(true);
    });

    it('names only the kinds whose hide toggle is on', () => {
      // An opened burst lifts hide_bursts: its repeats are on screen, so only the blink is hidden.
      mockStore.hiddenSummary.set({ total: 1, blinks: 1, bursts: 2, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_bursts: false, hide_blinks: true });
      const text = stack(render())!.querySelector('[role="status"]')!.textContent!;
      expect(text).toContain(I18N.gallery.hidden_banner.reason_blinks);
      expect(text).not.toContain(I18N.gallery.hidden_banner.reason_bursts);
    });

    it('the set-scope bar adds nothing when the whole set is on screen', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '161' });
      const html = render();
      const bar = Array.from(html.querySelectorAll('mat-sidenav-content > div'))
        .find(el => el.textContent?.includes(I18N.gallery.set_scope.message))!;
      expect(bar.textContent).not.toContain(I18N.gallery.set_scope.partial);
      expect(Array.from(bar.querySelectorAll('button')).some(b => b.textContent?.includes(I18N.gallery.hidden_banner.show_all))).toBe(false);
    });

    it('renders the restore twin once Show all has been used', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      const html = render();
      expect(stack(html)?.textContent).toContain(I18N.gallery.hidden_banner.showing_all);
      button(html, I18N.gallery.hidden_banner.restore)?.click();
      expect(mockStore.restoreHidden).toHaveBeenCalled();
    });

    it('stacks the migration notice below the hidden notice and its close removes only it', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      const cards = Array.from(stack(html)!.querySelectorAll('[role="status"]'));
      expect(cards).toHaveLength(2);
      expect(cards[0].textContent).toContain(I18N.gallery.hidden_banner.message);
      expect(cards[1].textContent).toContain(I18N.gallery.render_migration.message);
      closeFor(html, I18N.gallery.render_migration.message).click();
      fixture.detectChanges();
      const left = Array.from(stack(html)!.querySelectorAll('[role="status"]'));
      expect(left).toHaveLength(1);
      expect(left[0].textContent).toContain(I18N.gallery.hidden_banner.message);
    });

    it('shows the migration command as its own muted line, the whole translated sentence', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) => (vars ? `${key} ${JSON.stringify(vars)}` : key));
      const html = render();
      const line = html.querySelector<HTMLElement>('[data-notice-kind="render_migration"] [data-render-migration-command]')!;
      expect(line.textContent?.trim()).toBe(`${I18N.gallery.render_migration.command_hint} ${JSON.stringify({ command: 'python facet.py --refresh-thumbnails' })}`);
      expect(line.className).toContain('text-xs');
      expect(line.className).toContain('block');
      expect(line.parentElement!.textContent).toContain(`${I18N.gallery.render_migration.message} ${JSON.stringify({ n: 12 })}`);
    });

    it('closes the hidden-photos notice without touching the filters, and reopens it when the hidden count changes', () => {
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      const before = mockStore.filters();
      closeFor(html, I18N.gallery.hidden_banner.message).click();
      fixture.detectChanges();
      expect(stack(html)).toBeNull();
      expect(mockStore.filters()).toBe(before);
      expect(mockStore.showAllHidden).not.toHaveBeenCalled();

      mockStore.hiddenSummary.set({ total: 9, blinks: 0, bursts: 7, duplicates: 0, brackets: 2, panoramas: 0 });
      fixture.detectChanges();
      expect(stack(html)?.textContent).toContain(I18N.gallery.hidden_banner.message);
    });

    it('keeps each scope\'s closed notice closed on return, and ignores re-sorting', () => {
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      closeFor(html, I18N.gallery.hidden_banner.message).click();
      fixture.detectChanges();
      mockStore.filters.set({ ...mockStore.filters(), sort: 'date_taken', sort_direction: 'ASC' });
      fixture.detectChanges();
      expect(stack(html)).toBeNull();

      const scopeA = mockStore.filters();
      mockStore.filters.set({ ...scopeA, tag: 'beach' });
      fixture.detectChanges();
      expect(stack(html)?.textContent).toContain(I18N.gallery.hidden_banner.message);
      closeFor(html, I18N.gallery.hidden_banner.message).click();
      fixture.detectChanges();

      mockStore.filters.set(scopeA);
      fixture.detectChanges();
      expect(stack(html)).toBeNull();
    });

    it('closes the resume bookmark without resuming, and reopens it for another remembered queue', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      closeFor(html, I18N.gallery.review_progress.browser).click();
      fixture.detectChanges();
      expect(stack(html)).toBeNull();
      expect(mockStore.continueReview).not.toHaveBeenCalled();

      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      fixture.detectChanges();
      expect(stack(html)).toBeNull();
      mockStore.reviewBookmark.set({ path: '/p2.jpg', filters: { tag: 'b' } });
      fixture.detectChanges();
      expect(stack(html)?.textContent).toContain(I18N.gallery.review_progress.browser);
    });

    it('closes the restore twin without restoring, and reopens it when the stashed toggles change', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      const fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      const before = mockStore.filters();
      closeFor(html, I18N.gallery.hidden_banner.showing_all).click();
      fixture.detectChanges();
      expect(stack(html)).toBeNull();
      expect(mockStore.restoreHidden).not.toHaveBeenCalled();
      expect(mockStore.filters()).toBe(before);

      mockStore.hiddenFiltersStash.set({
        hide_blinks: false, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      fixture.detectChanges();
      expect(stack(html)?.textContent).toContain(I18N.gallery.hidden_banner.showing_all);
    });

    it('anchors the stack bottom-right, clear of an open end drawer and the content scrollbar', () => {
      vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
      const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 600, width: right - left, height: 600, x: left, y: 0, toJSON() { return {}; } });
      const original = HTMLElement.prototype.getBoundingClientRect;
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        if (this.classList.contains('relative') && this.classList.contains('h-full')) return rect(0, 1000) as DOMRect;
        if (this.tagName === 'MAT-SIDENAV-CONTENT') return rect(0, 700) as DOMRect;
        return original.call(this);
      });
      vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
        return this.tagName === 'MAT-SIDENAV-CONTENT' ? 683 : 0;
      });
      try {
        const fixture = TestBed.createComponent(GalleryComponent);
        Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(true), configurable: true });
        Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(true), configurable: true });
        mockStore.filterDrawerOpen.set(true);
        fixture.detectChanges();
        const notices = stack(fixture.nativeElement as HTMLElement)!;
        expect(notices.classList.contains('left-2')).toBe(false);
        // 1000 - (0 + 683) = 317 (drawer + scrollbar) plus the margin.
        expect(parseFloat(notices.style.right)).toBeGreaterThanOrEqual(317 + 8);
      } finally {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
      }
    });

    it('renders no stack when nothing is advisory', () => {
      mockStore.hiddenSummary.set({ total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 });
      expect(stack(render())).toBeNull();
    });

  });

  describe('docked details panel (tooltip_mode = panel)', () => {
    const hoverEvent = { currentTarget: null } as unknown as MouseEvent;

    /** Force the rail's width gate on, the way a >=1280px viewport would. */
    function widenForRail() {
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {},
      }));
      (component as unknown as { railWide: { setup(): void } }).railWide.setup();
    }

    beforeEach(() => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('needs a wide viewport as well as the setting, not the setting alone', () => {
      expect(component['tooltipMode']()).toBe('panel');
      expect(component.panelMode()).toBe(false);
    });

      describe('where the rail cannot dock (narrow or touch viewport)', () => {
        const cardEvent = () => ({
          currentTarget: {
            closest: () => ({
              getBoundingClientRect: () => ({ left: 120, right: 320, top: 120, height: 160, width: 200 }),
              querySelector: () => null,
            }),
          },
        }) as unknown as MouseEvent;

        it('the fallback targets a card so the placement maths run for the floating bubble', () => {
          const photo = { path: '/a.jpg' } as never;
          component.showTooltip(cardEvent(), photo);
          expect(component['tooltipPhoto']()).toBe(photo);
          expect(component['tooltipX']()).not.toBe(0);
        });

        it('Escape closes the floating fallback before touching the selection', () => {
          const photo = { path: '/a.jpg' };
          mockStore.photos.set([photo]);
          component.showTooltip(cardEvent(), photo as never);
          mockStore.selectedPaths.set(new Set([photo.path]));
          (component as unknown as { onGridKeydown(e: unknown): void })
            .onGridKeydown({ key: 'Escape', preventDefault: vi.fn() });
          expect(component['tooltipPhoto']()).toBeNull();
          expect(mockStore.clearSelection).not.toHaveBeenCalled();
        });
      });

    describe('with a viewport wide enough for the rail', () => {
      beforeEach(() => widenForRail());

      it('is active', () => {
        expect(component.panelMode()).toBe(true);
      });

      it('hovering a photo feeds the rail without any placement maths', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        expect(component['tooltipPhoto']()).toBe(photo);
        expect(component['tooltipX']()).toBe(0);
        expect(component['tooltipY']()).toBe(0);
      });

      it('keeps the last photo when the cursor leaves the grid', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        component.hideTooltip();
        expect(component['tooltipPhoto']()).toBe(photo);
      });

      it('keeps the inspected photo and open rail when another page is appended', () => {
        const photo = makePhoto({ path: '/a.jpg' });
        mockStore.photos.set([photo]); TestBed.tick();
        component.showTooltip(hoverEvent, photo);
        mockStore.photos.set([photo, makePhoto({ path: '/b.jpg' })]); TestBed.tick();
        expect(component['tooltipPhoto']()?.path).toBe('/a.jpg');
        expect(component.detailsRailVisible()).toBe(true);
      });

      describe('while a photo is current', () => {
        const a = { path: '/a.jpg' };
        const b = { path: '/b.jpg' };
        const panelPhoto = () => (component as unknown as { panelPhoto(): unknown }).panelPhoto();
        const release = () => (component as unknown as { releasePanel(): void }).releasePanel();

        beforeEach(() => {
          mockStore.toggleSelection.mockImplementation((photo: Photo) => {
            const selected = new Set<string>(mockStore.selectedPaths());
            if (mockStore.viewScopeSelected()) {
              const excluded = new Set<string>(mockStore.excludedPaths());
              if (excluded.has(photo.path)) excluded.delete(photo.path); else excluded.add(photo.path);
              mockStore.excludedPaths.set(excluded);
            } else {
              if (selected.has(photo.path)) selected.delete(photo.path); else selected.add(photo.path);
              mockStore.selectedPaths.set(selected);
              mockStore.selectionCount.set(selected.size);
            }
          });
          mockStore.photos.set([a, b]);
          click(a, 0);
          component.showTooltip(hoverEvent, a as never);
        });

        it('releases A when a second click actually deselects A', () => {
          expect(mockStore.selectedPaths().has(a.path)).toBe(true);
          click(a, 0);
          expect(mockStore.selectedPaths().has(a.path)).toBe(false);
          expect(hasActivePhoto()).toBe(false);
          component.showTooltip(hoverEvent, b as never);
          expect(panelPhoto()).toBe(b);
        });

        it('releases B after A then B then B, and follows subsequent hover', () => {
          click(b, 1); expect(activeIndex()).toBe(1);
          click(b, 1);
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.selectedPaths().has(a.path)).toBe(true);
          expect(mockStore.selectedPaths().has(b.path)).toBe(false);
          component.showTooltip(hoverEvent, a as never);
          expect(panelPhoto()).toBe(a);
        });

        it('releases an excluded card in a whole-view selection', () => {
          mockStore.viewScopeSelected.set(true);
          mockStore.excludedPaths.set(new Set());
          click(a, 0);
          expect(mockStore.excludedPaths().has(a.path)).toBe(true);
          expect(hasActivePhoto()).toBe(false);
        });

        it('hovering another photo does not retarget the rail', () => {
          component.showTooltip(hoverEvent, b as never);
          expect(panelPhoto()).toBe(a);
        });

        it('Deselect drops the cursor and the selection, keeps the photo until the next hover', () => {
          mockStore.selectedPaths.set(new Set([a.path]));
          component.showTooltip(hoverEvent, b as never);
          release();
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).toHaveBeenLastCalledWith(a);
          expect(panelPhoto()).toBe(a);
          component.showTooltip(hoverEvent, b as never);
          expect(panelPhoto()).toBe(b);
        });

        it('a new pin empties the rail and drops the cursor, so nothing of the previous view carries over', () => {
          TestBed.tick();
          component.showTooltip(hoverEvent, a as never);
          expect(panelPhoto()).toBe(a);
          mockStore.pinnedPaths.set(['/a.jpg']);
          TestBed.tick();
          expect(panelPhoto()).toBeFalsy();
          expect(hasActivePhoto()).toBe(false);
          expect(component['tooltipPhoto']()).toBeNull();
        });

        it('a plain filter reload with no pin leaves the held photo alone', () => {
          TestBed.tick();
          component.showTooltip(hoverEvent, a as never);
          mockStore.pinnedPaths.set(null);
          TestBed.tick();
          expect(component['tooltipPhoto']()).toBe(a);
          expect(hasActivePhoto()).toBe(true);
        });

        it('Deselect leaves an already-unselected photo unselected', () => {
          mockStore.selectedPaths.set(new Set());
          mockStore.toggleSelection.mockClear();
          release();
          expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        });

        it('Escape in the grid releases the photo like Deselect, then clears the rest of the selection', () => {
          mockStore.selectedPaths.set(new Set([a.path, b.path]));
          mockStore.selectionCount.set(2);
          component.showTooltip(hoverEvent, b as never);
          press('Escape');
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).toHaveBeenLastCalledWith(a);
          expect(mockStore.clearSelection).toHaveBeenCalled();
          expect(panelPhoto()).toBe(a);
        });

        it('Escape in the grid releases a photo the cursor holds without any selection', () => {
          mockStore.selectedPaths.set(new Set());
          mockStore.selectionCount.set(0);
          mockStore.toggleSelection.mockClear();
          press('Escape');
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).not.toHaveBeenCalled();
          expect(mockStore.clearSelection).not.toHaveBeenCalled();
        });

        it('Escape with one photo in a view-scoped selection still clears the store selection', () => {
          mockStore.photos.set([a]);
          mockStore.viewScopeSelected.set(true);
          // The store's count is "loaded photos minus exclusions"; the release excludes the only one.
          mockStore.selectionCount.set(0);
          mockStore.clearSelection.mockClear();
          press('Escape');
          expect(mockStore.clearSelection).toHaveBeenCalled();
          mockStore.viewScopeSelected.set(false);
          mockStore.selectionCount.set(0);
        });

        it('focus moving into the rail keeps the cursor', () => {
          const rail = document.createElement('div');
          rail.setAttribute('data-details-rail', '');
          const button = document.createElement('button');
          rail.appendChild(button);
          document.body.appendChild(rail);
          (component as unknown as { onGridFocusOut(e: FocusEvent): void })
            .onGridFocusOut({ relatedTarget: button } as unknown as FocusEvent);
          expect(activeIndex()).toBe(0);
          rail.remove();
        });
      });

      describe('after Escape released a held card that still has focus', () => {
        const four = [{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }, { path: '/d.jpg' }];
        let card: HTMLElement;
        let inner: HTMLElement;
        const fire = (key: string, target: HTMLElement) => {
          const ev = new KeyboardEvent('keydown', { key, cancelable: true });
          Object.defineProperty(ev, 'target', { value: target, configurable: true });
          (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
        };

        beforeEach(() => {
          mockStore.photos.set(four);
          mockStore.config.set({ features: { show_rating_controls: true } });
          (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
          card = document.createElement('div');
          card.setAttribute('data-pidx', '2');
          inner = document.createElement('span');
          card.appendChild(inner);
          click(four[2], 2);
          fire('Escape', inner);
          expect(activeIndex()).toBe(-1);
        });

        it('a rating key rates the card that has focus, not photo 0', () => {
          fire('5', inner);
          expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 5);
          expect(mockStore.setRating).not.toHaveBeenCalledWith('/a.jpg', 5);
        });

        it('ArrowRight moves on from the card that has focus', () => {
          fire('ArrowRight', inner);
          expect(activeIndex()).toBe(3);
        });
      });

      it('Escape in Hover mode never touches the panel hold: it only clears the selection', () => {
        mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
        click({ path: '/b.jpg' }, 1);
        mockStore.selectionCount.set(1);
        mockStore.toggleSelection.mockClear();
        mockStore.clearSelection.mockClear();
        press('Escape');
        expect(mockStore.clearSelection).toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(activeIndex()).toBe(1);
        mockStore.selectionCount.set(0);
      });

      it('keeps the grid at full width until a photo is chosen, then opens the rail once and keeps it', () => {
        const photo = makePhoto({ path: '/a.jpg', filename: 'a.jpg' });
        mockStore.photos.set([photo]);
        Object.assign(mockApi, { get: vi.fn(() => of({})) });
        const fixture = TestBed.createComponent(GalleryComponent);
        (fixture.componentInstance as unknown as { railWide: { setup(): void } }).railWide.setup();
        fixture.detectChanges();
        const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
        expect(fixture.componentInstance.panelMode()).toBe(true);
        expect(fixture.componentInstance.detailsRailVisible()).toBe(false);
        expect(fixture.nativeElement.querySelector('[data-details-rail]')).toBeNull();
        expect(drawer.opened).toBe(false);
        const open = vi.spyOn(drawer, 'open');
        const close = vi.spyOn(drawer, 'close');
        fixture.componentInstance.showTooltip(hoverEvent, photo);
        fixture.detectChanges();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(fixture.nativeElement.querySelector('[data-details-rail]')).not.toBeNull();
        expect(open).toHaveBeenCalled();
        const opened = open.mock.calls.length;
        // Hovering off the grid and across the next card never closes or reopens the strip.
        fixture.componentInstance.hideTooltip();
        fixture.detectChanges();
        fixture.componentInstance.showTooltip(hoverEvent, makePhoto({ path: '/b.jpg' }));
        fixture.componentInstance.hideTooltip();
        fixture.detectChanges();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(open.mock.calls.length).toBe(opened);
        expect(close).not.toHaveBeenCalled();
        fixture.destroy();
      });

      it('a reload that drops the held photo keeps the rail open on its empty state, for a hovered photo and for the cursor', () => {
        // Closing would widen the grid under a still pointer, and the card that lands under it would
        // reopen the rail on a photo nobody chose: two reflows for one re-sort.
        const a = makePhoto({ path: '/a.jpg', filename: 'a.jpg' });
        const b = makePhoto({ path: '/b.jpg', filename: 'b.jpg' });
        mockStore.photos.set([a, b]);
        Object.assign(mockApi, { get: vi.fn(() => of({})) });
        const fixture = TestBed.createComponent(GalleryComponent);
        const instance = fixture.componentInstance as unknown as { railWide: { setup(): void }; setCursor(index: number): void; hasActivePhoto(): boolean; panelPhoto(): { path: string } | null };
        instance.railWide.setup();
        fixture.detectChanges();
        const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
        fixture.componentInstance.showTooltip(hoverEvent, a);
        fixture.detectChanges();
        // A hover leaving the grid keeps the rail and its photo.
        fixture.componentInstance.hideTooltip();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        const close = vi.spyOn(drawer, 'close');
        mockStore.photos.set([b]);
        fixture.detectChanges();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(instance.panelPhoto()).toBeNull();
        const rail = () => fixture.nativeElement.querySelector('[data-details-rail]') as HTMLElement | null;
        expect(rail()?.textContent).toContain(I18N.gallery.tooltip_mode.panel_empty);
        instance.setCursor(0);
        fixture.detectChanges();
        expect(instance.panelPhoto()?.path).toBe('/b.jpg');
        mockStore.photos.set([makePhoto({ path: '/z.jpg' })]);
        fixture.detectChanges();
        expect(instance.hasActivePhoto()).toBe(false);
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(rail()?.textContent).toContain(I18N.gallery.tooltip_mode.panel_empty);
        expect(close).not.toHaveBeenCalled();
        fixture.destroy();
      });

      it('Escape in a rail opened by hover alone hands focus to the gallery, never to the page body', () => {
        const a = makePhoto({ path: '/a.jpg', filename: 'a.jpg' });
        mockStore.photos.set([a]);
        Object.assign(mockApi, { get: vi.fn(() => of({})) });
        const fixture = TestBed.createComponent(GalleryComponent);
        (fixture.componentInstance as unknown as { railWide: { setup(): void } }).railWide.setup();
        document.body.appendChild(fixture.nativeElement);
        fixture.detectChanges();
        fixture.componentInstance.showTooltip(hoverEvent, a);
        fixture.detectChanges();
        const rail = fixture.nativeElement.querySelector('[data-details-rail]') as HTMLElement;
        rail.focus();
        expect(document.activeElement).toBe(rail);
        rail.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
        fixture.detectChanges();
        expect(fixture.nativeElement.querySelector('[data-details-rail]')).toBeNull();
        const card = fixture.nativeElement.querySelector('[data-pidx="0"]') as HTMLElement | null;
        const landed = document.activeElement as HTMLElement;
        expect(landed).not.toBe(document.body);
        expect(card ? card.contains(landed) : !!landed.closest('[role="grid"], [data-photo-collection]')).toBe(true);
        fixture.destroy();
      });

      it('disableClose follows the rail: false while the filters occupy the drawer', () => {
        mockStore.photos.set([makePhoto({ path: '/inspected.jpg', filename: 'inspected.jpg' })]);
        Object.assign(mockApi, { get: vi.fn(() => of({})) });
        const fixture = TestBed.createComponent(GalleryComponent);
        (fixture.componentInstance as unknown as { railWide: { setup(): void } }).railWide.setup();
        fixture.componentInstance['setCursor'](0);
        fixture.detectChanges();
        const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(drawer.disableClose).toBe(true);
        mockStore.filterDrawerOpen.set(true);
        fixture.detectChanges();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(false);
        expect(drawer.disableClose).toBe(false);
        fixture.destroy();
      });

      describe('rail rendered with a held photo', () => {
        interface RailInstance {
          railWide: { setup(): void };
          hasActivePhoto(): boolean;
          setCursor(index: number): void;
        }
        let fixture: ComponentFixture<GalleryComponent>;
        let instance: RailInstance;
        let rail: HTMLElement;

        beforeEach(() => {
          const a = {
            path: '/a.jpg', filename: 'a.jpg', image_width: 4000, image_height: 3000, tags_list: [], persons: [],
          };
          mockStore.photos.set([a]);
          // The docked tooltip fetches its own extras (histogram, captions) once it renders.
          Object.assign(mockApi, { get: vi.fn(() => of({})) });
          fixture = TestBed.createComponent(GalleryComponent);
          instance = fixture.componentInstance as unknown as RailInstance;
          instance.railWide.setup();
          fixture.detectChanges();
          instance.setCursor(0);
          fixture.detectChanges();
          expect(instance.hasActivePhoto()).toBe(true);
          rail = fixture.nativeElement.querySelector('[data-details-rail]') as HTMLElement;
        });

        afterEach(() => fixture.destroy());

        const escape = (target: HTMLElement) => target.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true,
        }));

        it('names the inspector owner and offers no close button (the Details mode is switched off in the Display menu)', () => {
          expect(rail.querySelector('[data-inspector-owner]')?.textContent).toContain('a.jpg');
          expect(rail.querySelector('[data-close-inspector]')).toBeNull();
        });

        it('Escape releases the photo and closes the rail through the latch, not through MatDrawer (rendered)', () => {
          // MatDrawer closes itself on an Escape from inside it unless disableClose is set; the
          // rail's own latch is what closes the strip now, so the drawer closes once, on purpose,
          // and the sync effect has nothing left to reopen.
          const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
          const open = vi.spyOn(drawer, 'open');
          const close = vi.spyOn(drawer, 'close');
          escape(rail);
          fixture.detectChanges();
          expect(instance.hasActivePhoto()).toBe(false);
          expect(fixture.componentInstance.detailsRailVisible()).toBe(false);
          expect(fixture.nativeElement.querySelector('[data-details-rail]')).toBeNull();
          expect(close).toHaveBeenCalled();
          expect(open).not.toHaveBeenCalled();
        });

        it('focus leaving the rail for the outside releases the hold', () => {
          const outside = document.createElement('button');
          document.body.appendChild(outside);
          rail.dispatchEvent(new FocusEvent('focusout', { relatedTarget: outside, bubbles: true }));
          expect(instance.hasActivePhoto()).toBe(false);
          outside.remove();
        });

        it('focus moving within the rail keeps the hold', () => {
          const inside = rail.querySelector('button') as HTMLElement;
          rail.dispatchEvent(new FocusEvent('focusout', { relatedTarget: inside, bubbles: true }));
          expect(instance.hasActivePhoto()).toBe(true);
        });

        it('Escape on the focused Deselect button closes the rail and never leaves focus inside it', () => {
          document.body.appendChild(fixture.nativeElement);
          const button = rail.querySelector('button') as HTMLElement;
          button.focus();
          escape(button);
          fixture.detectChanges();
          expect(fixture.nativeElement.querySelector('[data-details-rail]')).toBeNull();
          expect(rail.contains(document.activeElement)).toBe(false);
        });

        it('Deselect closes the rail, and the next photo to enter it opens it again', () => {
          (rail.querySelector('button') as HTMLButtonElement).click();
          fixture.detectChanges();
          expect(fixture.componentInstance.detailsRailVisible()).toBe(false);
          fixture.componentInstance.showTooltip(hoverEvent, mockStore.photos()[0]);
          fixture.detectChanges();
          expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        });

        it('the score-explainer entry opens the critique for the held photo', () => {
          mockStore.config.set({ features: { show_critique: true } });
          fixture.detectChanges();
          const openCritique = vi.spyOn(fixture.componentInstance, 'openCritique');
          const entry = rail.querySelector('app-photo-assessment [data-explain-score]') as HTMLElement | null;
          expect(entry).toBeTruthy();
          expect(entry!.getAttribute('aria-label')).toBe(I18N.critique.title);
          entry!.click();
          expect(openCritique).toHaveBeenLastCalledWith(mockStore.photos()[0]);
        });

        it('the score-explainer entry stays hidden when the install hides the explainer', () => {
          mockStore.config.set({ features: { show_critique: false } });
          fixture.detectChanges();
          expect(rail.querySelector('[data-explain-score]')).toBeNull();
        });
      });

      it('yields the shared drawer to the filters while they are open', () => {
        mockStore.filterDrawerOpen.set(true);
        expect(component.detailsRailVisible()).toBe(false);
      });
    });

    it('still clears on mouse-out in hover mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });

    it('falls back to a positioned floating tooltip when the rail cannot be shown', () => {
      // Selecting the mode on a viewport too narrow for the rail used to skip
      // the placement maths and leave the floating box at a stale coordinate.
      const card = document.createElement('div');
      card.className = 'relative rounded-lg';
      document.body.appendChild(card);
      const photo = { path: '/a.jpg', image_width: 4000, image_height: 3000 } as never;
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);
      card.remove();
    });

    it('clears on mouse-out while the rail is unavailable, like hover does', () => {
      const photo = { path: '/a.jpg' } as never;
      component['tooltipPhoto'].set(photo);
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });
  });

  describe('tooltip mode switch clears a stale tooltipPhoto', () => {
    function makeCard(): HTMLElement {
      const card = document.createElement('div');
      card.className = 'relative rounded-lg';
      document.body.appendChild(card);
      return card;
    }
    const photo = { path: '/a.jpg', image_width: 4000, image_height: 3000 } as never;

    it('a hover-shown tooltip does not survive a switch to click mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('the first click in the new mode shows the tooltip rather than hiding it', () => {
      // A test asserting only "clicking twice toggles" would pass even if a
      // stale hover-set tooltipPhoto made this very first click hide instead
      // of show -- assert the show explicitly.
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      expect(component['tooltipPhoto']()).toBe(photo);
      card.remove();
    });

    it('a click-pinned tooltip does not survive a switch to hover mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('Escape closes a click-opened tooltip first and leaves the selection for the next Escape', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.selectionCount.set(1);
      mockStore.clearSelection.mockClear();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      press('Escape');
      expect(component['tooltipPhoto']()).toBeNull();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();

      press('Escape');
      expect(mockStore.clearSelection).toHaveBeenCalled();
      mockStore.selectionCount.set(0);
      card.remove();
    });

    it('a tooltip does not survive a switch to off mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'off' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('switching into panel mode does not carry over a stale hover tooltip', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });
  });

  describe('catalog-only selection removal', () => {
    it('passes only the explicit captured paths to the catalog action', async () => {
      const remove = vi.spyOn(TestBed.inject(PhotoActionsService), 'removeFromCatalog').mockResolvedValue(['/a.jpg']);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      await component.selectionActions.removeSelectedFromCatalog();
      expect(remove).toHaveBeenCalledExactlyOnceWith(['/a.jpg', '/b.jpg']);
      expect(mockStore.selectedPaths()).toEqual(new Set(['/a.jpg', '/b.jpg']));
    });

    it('refuses whole-view scope rather than materializing it into catalog deletion', async () => {
      const remove = vi.spyOn(TestBed.inject(PhotoActionsService), 'removeFromCatalog').mockResolvedValue([]);
      mockStore.viewScopeSelected.set(true);
      await component.selectionActions.removeSelectedFromCatalog();
      expect(remove).not.toHaveBeenCalled();
    });
  });

  describe('compare selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The workspace owns its own tests; this checks captured membership and entry.
    it('is offered from two photos up to the queue limit', () => {
      const c = component as unknown as { canCompareSelection: () => boolean };
      for (const n of [0, 1]) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(false);
      }
      for (const n of [2, 4, 12, MAX_COMPARE_QUEUE]) {
        const paths = Array.from({ length: n }, (_, i) => `/p${i}.jpg`);
        mockStore.photos.set(paths.map(photo));
        select(paths);
        expect(c.canCompareSelection()).toBe(true);
      }
      const oversized = Array.from({ length: MAX_COMPARE_QUEUE + 1 }, (_, i) => `/p${i}.jpg`);
      mockStore.photos.set(oversized.map(photo)); select(oversized);
      expect(c.canCompareSelection()).toBe(false);
    });

    it('hands over the grid order, not the order they were picked in', async () => {
      mockStore.photos.set(['/a.jpg', '/b.jpg', '/c.jpg'].map(photo));
      select(['/c.jpg', '/a.jpg']);
      const router = TestBed.inject(Router);
      const navigate = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
      const capture = vi.spyOn(TestBed.inject(ComparisonSessionService), 'start');
      await component['compareSelection']();
      const data = TestBed.inject(ComparisonSessionService).snapshot();
      expect(data.photos.map(p => p.path)).toEqual(['/a.jpg', '/c.jpg']);
      expect(capture).toHaveBeenCalledOnce();
      expect(capture.mock.calls[0][0].map(p => p.path)).toEqual(['/a.jpg', '/c.jpg']);
      expect(capture.mock.calls[0][1]).toBe(router.url);
      expect(navigate).toHaveBeenCalledExactlyOnceWith('/photo-compare', { state: { comparisonReturn: TestBed.inject(Router).url, comparisonOriginId: null } });
      expect(TestBed.inject(MatDialog).open).not.toHaveBeenCalled();
    });

    it('refuses an oversized selection instead of silently comparing a subset', async () => {
      const paths = Array.from({ length: MAX_COMPARE_QUEUE + 2 }, (_, i) => `/p${i}.jpg`);
      mockStore.photos.set(paths.map(photo));
      select(paths);
      const capture = vi.spyOn(TestBed.inject(ComparisonSessionService), 'start');
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect(capture).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('discloses unloaded selected paths and refuses partial comparison until all selected photos load', async () => {
      mockStore.photos.set([photo('/a.jpg'), photo('/b.jpg')]);
      select(['/a.jpg', '/b.jpg', '/elsewhere.jpg']);
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      expect(root.querySelector('[data-selection-outside]')?.textContent).toContain(I18N.gallery.selection.outside_loaded);
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.gallery.selection.outside_loaded, { count: 1 });
      const button = root.querySelector<HTMLButtonElement>(`button[aria-label="${I18N.gallery.selection.compare}"]`)!;
      expect(button.disabled).toBe(false);
      expect(button.getAttribute('aria-disabled')).toBe('true');
      expect(button.getAttribute('aria-describedby')).toBe('compare-selection-requirements');
      const capture = vi.spyOn(TestBed.inject(ComparisonSessionService), 'start');
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
      await component['compareSelection']();
      expect(capture).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
      mockStore.photos.set([photo('/a.jpg'), photo('/b.jpg'), photo('/elsewhere.jpg')]);
      fixture.detectChanges();
      expect(root.querySelector('[data-selection-outside]')).toBeNull();
      expect(button.disabled).toBe(false);
      fixture.destroy();
    });

    it('does nothing when fewer than two selected photos are loaded', async () => {
      mockStore.photos.set([photo('/a.jpg')]);
      select(['/a.jpg', '/gone.jpg']);
      const capture = vi.spyOn(TestBed.inject(ComparisonSessionService), 'start');
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect(capture).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('openCullDialog', () => {
    beforeEach(() => { mockAuth['isEdition'] = vi.fn(() => true); });
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog itself is covered by its own spec; this is the wiring — which
    // capability flags reach it, and that both read fail-closed off the config.
    it('passes trashAvailable and allowTrash through when both are enabled', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(true);
      expect(data.allowTrash).toBe(true);
    });

    it('passes allowTrash true but trashAvailable false when the package is missing', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: false } });
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(false);
      expect(data.allowTrash).toBe(true);
    });

    it('fails closed to both false when the config has no cull key at all', async () => {
      mockStore.config.set({});
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(false);
      expect(data.allowTrash).toBe(false);
    });

    it('reloads the list before clearing the selection', async () => {
      // Clearing hands focus back to the marked card, and until the reload
      // returns the rows the cull has just moved away are still in the list --
      // so the focus would be aimed at a photo that no longer exists.
      mockStore.config.set({});
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      const order: string[] = [];
      mockStore.reloadPhotos.mockImplementation(() => {
        order.push('load');
        return Promise.resolve();
      });
      mockStore.clearSelection.mockImplementation(() => order.push('clear'));

      await component.selectionActions.openCullDialog();

      expect(order).toEqual(['load', 'clear']);
    });

    it.each(['navigation', 'identity', 'edition', 'filters'])(
      'does not refresh or clear a newer gallery after cull loses %s', async loss => {
        mockAuth['isEdition'] = vi.fn(() => true);
        select(['/a.jpg']);
        const result = new Subject<boolean>();
        const dialog = TestBed.inject(MatDialog);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => result });
        const pending = component.selectionActions.openCullDialog();
        await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
        if (loss === 'navigation')
          (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, '/other'));
        if (loss === 'identity') (mockAuth['status'] as ReturnType<typeof signal>).set({ user_id: 'bob' });
        if (loss === 'edition') mockAuth['isEdition'] = vi.fn(() => false);
        if (loss === 'filters') mockStore.filterPayload.mockReturnValue({ camera: 'Nikon' });
        select(['/new.jpg']);
        result.next(true); result.complete(); await pending;
        expect(mockStore.reloadPhotos).not.toHaveBeenCalled();
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect([...mockStore.selectedPaths()]).toEqual(['/new.jpg']);
      },
    );

    it('does not clear a new selection when navigation starts during the post-cull reload', async () => {
      mockAuth['isEdition'] = vi.fn(() => true);
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      let finish!: () => void;
      mockStore.reloadPhotos.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
      const pending = component.selectionActions.openCullDialog();
      await vi.waitFor(() => expect(mockStore.reloadPhotos).toHaveBeenCalled());
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, '/other'));
      select(['/new.jpg']); finish(); await pending;
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect([...mockStore.selectedPaths()]).toEqual(['/new.jpg']);
    });

    // The guard reads `if (!viewScoped && !paths.length) return;` -- widened
    // specifically so a whole-view cull (selectedPaths empty by design) is not
    // silently dropped the way `if (!paths.length) return;` would drop it.
    it('still opens under view scope even though selectedPaths is empty', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      mockStore.selectionScope.set('view');
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.openCullDialog();

      expect(dialog.open).toHaveBeenCalled();
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.filters).toEqual({ page: '1' });
      expect(data.exclude).toEqual(['/skip.jpg']);
      expect(data.count).toBe(650);
    });
  });

  describe('capture-date targets', () => {
    beforeEach(() => { mockAuth['isEdition'] = vi.fn(() => true); });
    it.each(['identity', 'edition', 'navigation', 'destroy'])('does not open after lazy date launch loses %s', async loss => {
      mockStore.selectedPaths.set(new Set(['/a'])); mockStore.selectionCount.set(1);
      const dialog = TestBed.inject(MatDialog);
      const task = component.selectionActions.openCaptureDateDialog();
      if (loss === 'identity') (mockAuth['status'] as ReturnType<typeof signal>).set({ user_id: 'bob' });
      if (loss === 'edition') mockAuth['isEdition'] = vi.fn(() => false);
      if (loss === 'navigation') {
        (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, '/other'));
        (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(2, '/'));
      }
      if (loss === 'destroy') TestBed.resetTestingModule();
      await task;
      expect(dialog.open).not.toHaveBeenCalled();
    });
    it('captures scope and exclusions before lazy loading the dialog', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(12);
      mockStore.filterPayload.mockReturnValue({ camera: 'Canon' });
      const dialog = TestBed.inject(MatDialog);
      const pending = component.selectionActions.openCaptureDateDialog();
      mockStore.filterPayload.mockReturnValue({ camera: 'Nikon' });
      mockStore.excludedPaths.set(new Set(['/new.jpg']));
      await pending;
      expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: [], filters: { camera: 'Canon' }, exclude: ['/skip.jpg'], count: 12, reference: null });
    });
    it('passes the first loaded, dated photo of an explicit selection as the reference', async () => {
      mockStore.photos.set([
        { path: '/undated.jpg', date_taken: null }, { path: '/other.jpg', date_taken: '2020:01:01 00:00:00' },
        { path: '/b.jpg', date_taken: '2024:05:06 07:08:09' },
      ] as never);
      mockStore.selectedPaths.set(new Set(['/undated.jpg', '/b.jpg'])); mockStore.selectionCount.set(2);
      const dialog = TestBed.inject(MatDialog);
      await component.selectionActions.openCaptureDateDialog();
      expect((dialog.open as Mock).mock.calls[0][1].data.reference).toEqual({ path: '/b.jpg', date: '2024:05:06 07:08:09' });
    });
  });

  describe('openBatchGpsDialog', () => {
    it.each(['identity', 'edition', 'navigation', 'destroy'])('does not open after lazy GPS launch loses %s', async loss => {
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.selectedPaths.set(new Set(['/a'])); mockStore.selectionCount.set(1);
      const dialog = TestBed.inject(MatDialog);
      const task = component.selectionActions.openBatchGpsDialog();
      if (loss === 'identity') (mockAuth['status'] as ReturnType<typeof signal>).set({ user_id: 'bob' });
      if (loss === 'edition') mockAuth['isEdition'] = vi.fn(() => false);
      if (loss === 'navigation') {
        (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, '/other'));
        (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(2, '/'));
      }
      if (loss === 'destroy') TestBed.resetTestingModule();
      await task;
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('captures the complete filter and exclusions before lazy loading the dialog', async () => {
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionCount.set(650);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      const filters = { no_gps: '1', camera: 'Canon' };
      (mockStore.filterPayload as Mock).mockReturnValue(filters);
      const pending = component.selectionActions.openBatchGpsDialog();
      filters.camera = 'Nikon';
      mockStore.excludedPaths.set(new Set(['/later.jpg']));
      await pending;
      const data = (TestBed.inject(MatDialog).open as Mock).mock.calls[0][1].data;
      expect(data.batch).toEqual({ filters: { no_gps: '1', camera: 'Canon' }, exclude: ['/skip.jpg'] });
    });

    it('clears the completed selection but preserves a newer selection', async () => {
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.selectionCount.set(2);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      const dialog = TestBed.inject(MatDialog);
      await component.selectionActions.openBatchGpsDialog();
      const applied = (dialog.open as Mock).mock.calls[0][1].data.onBatchApplied;
      applied();
      expect(mockStore.clearSelection).toHaveBeenCalledTimes(1);
      (mockStore.clearSelection as Mock).mockClear();
      mockStore.selectedPaths.set(new Set(['/new.jpg']));
      applied();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('opens the shared GPS dialog for explicit selection and refuses read-only access', async () => {
      mockStore.selectionCount.set(2);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      const dialog = TestBed.inject(MatDialog);
      await component.selectionActions.openBatchGpsDialog();
      expect(dialog.open).not.toHaveBeenCalled();
      mockAuth['isEdition'] = vi.fn(() => true);
      await component.selectionActions.openBatchGpsDialog();
      expect((dialog.open as Mock).mock.calls[0][1].data.batch).toEqual({ photo_paths: ['/a.jpg', '/b.jpg'] });
    });
  });

  describe('openManualTagsDialog', () => {
    beforeEach(() => { mockAuth['isEdition'] = vi.fn(() => true); mockStore.refreshPaths = vi.fn(() => Promise.resolve()); mockStore.pathsInView = vi.fn(async () => ['/matching-cover', '/matching-member']); });
    const open = () => component.selectionActions.openManualTagsDialog();
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    it('refuses a tag preview when view criteria or exclusions change while resolving paths', async () => {
      mockStore.viewScopeSelected.set(true);
      const filters = { tag: 'old' };
      mockStore.filterPayload = vi.fn(() => filters);
      mockStore.excludedPaths.set(new Set(['/old-skip']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });
      const pending = open();
      filters.tag = 'new';
      mockStore.excludedPaths.set(new Set(['/new-skip']));
      mockStore.selectionCount.set(1);
      await pending;
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('refuses a late launch after edition access is lost', async () => {
      select(['/a.jpg']);
      const pending = open();
      mockAuth['isEdition'] = vi.fn(() => false);
      await pending;
      expect(TestBed.inject(MatDialog).open).not.toHaveBeenCalled();
    });

    it('repairs a sent write that settles after the dialog has already closed', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });
      await open();
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      data.onSettled({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: true, uncertain: false });
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
      const status = mockAuth['status'] as WritableSignal<Record<string, unknown>>;
      status.set({ ...status(), user_id: 'other' });
      data.onSettled({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: true, uncertain: false });
      expect(mockStore.refreshPaths).toHaveBeenCalledTimes(1);
    });

    it('repairs a settlement once when both writer and dialog close deliver it', async () => {
      select(['/a.jpg']);
      const result = { confirmedCount: 1, tag: 'trip', action: 'add', incomplete: false, uncertain: false };
      (TestBed.inject(MatDialog).open as Mock).mockImplementation((_component, config) => {
        config.data.onSettled(result);
        return { afterClosed: () => of(result) };
      });
      await open();
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
    });

    it('refreshes the captured paths without restoring over a newer selection', async () => {
      select(['/a.jpg']);
      const closed = new Subject<unknown>();
      let didOpen!: () => void;
      const opened = new Promise<void>(resolve => { didOpen = resolve; });
      (TestBed.inject(MatDialog).open as Mock).mockImplementation(() => { didOpen(); return { afterClosed: () => closed }; });
      const pending = open();
      await opened;
      select(['/new.jpg']);
      closed.next({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: false, uncertain: false });
      await pending;
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
      expect([...mockStore.selectedPaths()]).toEqual(['/new.jpg']);
      expect(mockStore.restoreSelection).not.toHaveBeenCalled();
    });

    it('refreshes accepted tags after photo navigation and outlet detachment park the gallery', async () => {
      select(['/a.jpg']);
      const closed = new Subject<unknown>();
      let didOpen!: () => void;
      const opened = new Promise<void>(resolve => { didOpen = resolve; });
      (TestBed.inject(MatDialog).open as Mock).mockImplementation(() => { didOpen(); return { afterClosed: () => closed }; });
      const pending = open();
      await opened;
      const router = TestBed.inject(Router);
      router.resetConfig([{ path: 'photo', component: MenuPhotoRoute }]);
      await router.navigateByUrl('/photo?path=%2Fa.jpg');
      outletMock.detachEvents.next(component);
      expect(mockStore.parkListingReads).toHaveBeenCalledOnce();
      closed.next({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: false, uncertain: false });
      await pending;
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
      expect(mockStore.restoreSelection).not.toHaveBeenCalled();
    });

    it('does not refresh a different principal after an accepted write completes', async () => {
      select(['/a.jpg']);
      const closed = new Subject<unknown>();
      let didOpen!: () => void;
      const opened = new Promise<void>(resolve => { didOpen = resolve; });
      (TestBed.inject(MatDialog).open as Mock).mockImplementation(() => { didOpen(); return { afterClosed: () => closed }; });
      const pending = open();
      await opened;
      const status = mockAuth['status'] as WritableSignal<Record<string, unknown>>;
      status.set({ ...status(), user_id: 'other' });
      closed.next({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: false, uncertain: false });
      await pending;
      expect(mockStore.refreshPaths).not.toHaveBeenCalled();
    });

    it('refreshes grouped-tag membership when a write settles in a newer view', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });
      await open();
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tag_groups: '{"all":["trip"]}' }));
      mockStore.photos.set([]);
      data.onSettled({ confirmedCount: 1, tag: 'trip', action: 'add', incomplete: true, uncertain: false });
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(null);
      expect(mockStore.restoreSelection).not.toHaveBeenCalled();
    });

    it('repairs tag-dependent membership even when a lost response confirms no count', async () => {
      select(['/a.jpg']);
      mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, search: 'trip' }));
      (TestBed.inject(MatDialog).open as Mock).mockReturnValue({ afterClosed: () => of({ confirmedCount: 0, tag: 'trip', action: 'add', incomplete: true, uncertain: true }) });
      await open();
      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(null);
      expect(mockStore.reloadPhotos).not.toHaveBeenCalled();
    });

    // The dialog owns its request (its own spec); this is the wiring.
    it('opens the manual-tags dialog with the selected paths', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      expect(dialog.open).toHaveBeenCalledTimes(1);
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.paths).toEqual(['/a.jpg', '/b.jpg']);
      expect(data.filters).toBeUndefined();
      expect(data.count).toBe(2);
    });

    it('captures resolved matching members and the actual count under view scope', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(mockStore.pathsInView).toHaveBeenCalledOnce();
      expect(data.paths).toEqual(['/matching-cover', '/matching-member']);
      expect(data.fromWholeView).toBe(true);
      expect(data.filters).toBeUndefined();
      expect(data.count).toBe(2);
    });

    it('does nothing for an empty path selection', async () => {
      select([]);
      const dialog = TestBed.inject(MatDialog);

      await open();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('refetches the list after a write, so the detail view gets fresh manual tags', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of({ confirmedCount: 1, action: 'add', tag: 'trip', incomplete: false, uncertain: false }) });

      await open();

      expect(mockStore.refreshPaths).toHaveBeenCalledExactlyOnceWith(['/a.jpg']);
      expect(mockStore.reloadPhotos).not.toHaveBeenCalled();
      expect(mockStore.restoreSelection).not.toHaveBeenCalled();
    });

    it('leaves the list alone when the dialog is cancelled', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
    });
  });

  describe('selection bar edit-tags button (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(edition: boolean): ComponentFixture<GalleryComponent> {
      mockAuth['isEdition'] = vi.fn(() => edition);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.config.set({});
      mockStore.selectionCount.set(2);
      mockStore.viewScopeSelected.set(false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return fixture;
    }

    function tagsButton(f: ComponentFixture<GalleryComponent>): HTMLButtonElement | null {
      const actions = openSelectionActions(f);
      if (!menuItem(actions, I18N.gallery.selection.edit_metadata)) return null;
      return menuItem(openSelectionSubmenu(f, actions, I18N.gallery.selection.edit_metadata), I18N.gallery.selection.edit_tags);
    }

    it('is a desktop Actions > Edit metadata entry for an edition user', () => {
      const f = render(true);
      const button = tagsButton(f);

      expect(button).not.toBeNull();
      expect(f.nativeElement.querySelector('[data-selection-more]').closest('.max-md\\:hidden')).not.toBeNull();
    });

    it('is absent without edition', () => {
      expect(tagsButton(render(false))).toBeNull();
    });

    it('opens the dialog when clicked', () => {
      const f = render(true);
      const open = vi.spyOn(f.componentInstance.selectionActions, 'openManualTagsDialog')
        .mockResolvedValue(undefined);

      tagsButton(f)!.click();

      expect(open).toHaveBeenCalledTimes(1);
    });
  });

  describe('deleteSelected', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    function deleteResponse(overrides: Partial<{
      deleted: string[]; refused_bracket_lead: string[]; not_found: string[];
      not_visible: string[]; sequence_siblings: string[]; skipped: string[]; removed_missing: string[];
      errors: Record<string, string>; trashed: number;
    }> = {}) {
      return of({
        dry_run: false,
        deleted: [],
        not_found: [],
        not_visible: [],
        refused_bracket_lead: [],
        sequence_siblings: [],
        skipped: [],
        removed_missing: [],
        trashed: 0,
        errors: {},
        ...overrides,
      });
    }

    // decision 8 / B5: `paths` cannot express a view-scoped selection, so the
    // toolbar button is disabled under it -- this is the belt-and-braces guard
    // behind that, proven directly rather than only via the disabled attribute.
    it('does nothing under view scope, even if somehow invoked', async () => {
      mockStore.viewScopeSelected.set(true);
      const dialog = TestBed.inject(MatDialog);

      await component.selectionActions.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('does nothing with an empty selection', async () => {
      select([]);
      const dialog = TestBed.inject(MatDialog);

      await component.selectionActions.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('opens the dialog with paths only (never filters/exclude) and hasCompanion always offered', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.deleteSelected();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.surface).toBe('bulk');
      expect(data.paths).toEqual(['/a.jpg', '/b.jpg']);
      expect(data.filters).toBeUndefined();
      expect(data.exclude).toBeUndefined();
      expect(data.hasCompanion).toBe(true);
      expect(data.hasBracketLead).toBe(false);
    });

    it('passes hasSiblings true when a selected, loaded photo carries a sequence_kind', async () => {
      mockStore.photos.set([
        { path: '/a.jpg', sequence_kind: 'bracket' },
        { path: '/b.jpg', sequence_kind: null },
      ]);
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(true);
    });

    it('passes hasSiblings false when no selected photo carries a bracket/panorama/hdr_panorama sequence_kind', async () => {
      mockStore.photos.set([{ path: '/a.jpg', sequence_kind: null }]);
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(false);
    });

    it('cancelling the dialog makes no request', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.selectionActions.deleteSelected();

      expect(mockApi.post).not.toHaveBeenCalledWith('/photo/delete', expect.anything());
      expect(mockStore.removePhotos).not.toHaveBeenCalled();
    });

    it('on confirm: posts dry_run=false, removes only the DELETED paths (not a refused one), clears the selection, and never refetches', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ deleted: ['/a.jpg'], refused_bracket_lead: ['/b.jpg'], trashed: 1 }),
      );

      await component.selectionActions.deleteSelected();

      expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', {
        paths: ['/a.jpg', '/b.jpg'],
        include_companions: false,
        include_sequence_siblings: false,
        remove_missing: false,
        dry_run: false,
      });
      // Restricted to what the response actually reports deleted -- a refused
      // bracket lead's row still exists server-side and must stay in the grid.
      expect(mockStore.removePhotos).toHaveBeenCalledWith(['/a.jpg']);
      expect(mockStore.clearSelection).toHaveBeenCalled();
      // Step 11 deliberately departs from cull's `loadPhotos()` reload pattern
      // for delete specifically -- guards against silently reverting to it.
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
    });

    it('reports a partial result snackbar with the deleted and failed counts', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ deleted: ['/a.jpg'], refused_bracket_lead: ['/b.jpg'], trashed: 1 }),
      );
      const snackBar = TestBed.inject(MatSnackBar);

      await component.selectionActions.deleteSelected();

      expect(snackBar.open).toHaveBeenCalledWith(
        mockI18n.t(I18N.cull.delete_partial_result, { deleted: 1, failed: 1 }),
        '', { duration: 4000 },
      );
    });

    // Finding 5: a bulk delete where every send2trash failed must not render
    // as a neutral "0 deleted, 0 refused" result -- `errors` (an unwritable
    // trash dir), `not_found`, `not_visible` and `skipped` all count as
    // failures even though none of them is `refused_bracket_lead`, the only
    // bucket the toast used to read.
    it('reports the dedicated delete_failed snackbar when every path lands in errors and none is deleted', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ errors: { '/a.jpg': 'Permission denied', '/b.jpg': 'Permission denied' } }),
      );
      const snackBar = TestBed.inject(MatSnackBar);

      await component.selectionActions.deleteSelected();

      expect(snackBar.open).toHaveBeenCalledWith(
        mockI18n.t(I18N.cull.delete_failed), '', { duration: 4000 },
      );
    });

    it('folds not_found, not_visible and skipped into the partial-result failed count, not just refused_bracket_lead', async () => {
      select(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({
          deleted: ['/a.jpg'], not_found: ['/b.jpg'], not_visible: ['/c.jpg'], skipped: ['/d.jpg'], trashed: 1,
        }),
      );
      await component.selectionActions.deleteSelected();

      // Asserted on the i18n mock's own call args, not on the snackbar's
      // resolved text: `mockI18n.t` ignores its `vars` argument and echoes
      // the key back, so `snackBar.open`'s first argument is identical
      // ("cull.delete_partial_result") whether `failed` is computed from all
      // four buckets or from `refused_bracket_lead` alone -- asserting on
      // that resolved string would pass under either implementation.
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.cull.delete_partial_result, { deleted: 1, failed: 3 });
    });

    it('removes reconciled missing rows from the grid and counts them as deleted', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false, removeMissing: true }),
      });
      mockApi.post.mockReturnValueOnce(deleteResponse({ removed_missing: ['/a.jpg', '/b.jpg'] }));

      await component.selectionActions.deleteSelected();

      expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', expect.objectContaining({ remove_missing: true }));
      expect(mockStore.removePhotos).toHaveBeenCalledWith(['/a.jpg', '/b.jpg']);
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.cull.delete_partial_result, { deleted: 2, failed: 0 });
    });

    it('a failed request does not touch the store', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));

      await component.selectionActions.deleteSelected();

      expect(mockStore.removePhotos).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });
  });

  // The desktop toolbar button and its gating -- the two properties the
  // adversarial review singled out (G13, B5): gated on `trash_available`
  // (never the raw `allow_trash`), and disabled (not hidden) under a
  // view-scoped selection because `paths` cannot express one.
  describe('bulk delete toolbar button (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(trashAvailable: boolean, viewScoped: boolean, allowTrash: boolean = trashAvailable): ComponentFixture<GalleryComponent> {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.config.set({ cull: { allow_trash: allowTrash, trash_available: trashAvailable } });
      mockStore.selectionCount.set(2);
      mockStore.viewScopeSelected.set(viewScoped);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return fixture;
    }

    function deleteButton(f: ComponentFixture<GalleryComponent>): HTMLButtonElement | null {
      return menuItem(openSelectionActions(f), I18N.cull.delete_action);
    }

    it('is absent when trash_available is false, even with allow_trash true', () => {
      const f = render(false, false, true);
      expect(deleteButton(f)).toBeNull();
    });

    it('is present and enabled when trash_available is true and the selection is an explicit path list', () => {
      const f = render(true, false);
      const button = deleteButton(f);
      expect(button).not.toBeNull();
      expect(button!.disabled).toBe(false);
      expect(button!.getAttribute('aria-disabled')).toBeNull();
    });

    it('is disabled under a view-scoped ("select all in view") selection, with a tooltip explaining why', () => {
      const f = render(true, true);
      const button = deleteButton(f);
      expect(button).not.toBeNull();
      // disabledInteractive: aria-disabled instead of the native attribute, so the tooltip still shows.
      expect(button!.getAttribute('aria-disabled')).toBe('true');
      expect(button!.disabled).toBe(false);
      const tooltipDebug = f.debugElement.queryAll(By.directive(MatTooltip))
        .find(de => de.nativeElement === button);
      expect(tooltipDebug?.injector.get(MatTooltip).message).toBe(I18N.cull.delete_disabled_view_scope_tooltip);
    });
  });

  // The selection bar is a floating contextual command bar inside the gallery host (not a
  // fixed full-width strip): placement, label reachability and the notice baseline.
  describe('floating selection card (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    });

    function render(opts: { edition?: boolean; desktop?: boolean; viewScoped?: boolean; profiles?: string[]; albums?: boolean; trash?: boolean } = {}): ComponentFixture<GalleryComponent> {
      const { edition = true, desktop = true, viewScoped = false, profiles = [], albums = true, trash = true } = opts;
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: desktop && media.includes('min-width: 768px'), media, addEventListener() {}, removeEventListener() {},
      }));
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => edition);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => profiles);
      mockStore.config.set({ cull: { allow_trash: true, trash_available: trash }, features: { show_albums: albums } });
      mockStore.selectionCount.set(2);
      mockStore.viewScopeSelected.set(viewScoped);
      fixture = TestBed.createComponent(GalleryComponent);
      // The breakpoint signal is wired in afterNextRender; wire it by hand, as the rail specs do.
      (fixture.componentInstance as unknown as { desktop: { setup(): void } }).desktop.setup();
      fixture.detectChanges();
      return fixture;
    }

    const bar = (f: ComponentFixture<GalleryComponent>) => f.nativeElement.querySelector('[data-selection-bar]') as HTMLElement | null;
    const labelled = (f: ComponentFixture<GalleryComponent>, label: string) =>
      bar(f)?.querySelector(`button[aria-label="${label}"]`) as HTMLButtonElement | null;

    it('floats absolutely inside the notice host, rounded, never fixed', () => {
      const f = render();
      const el = bar(f)!;
      expect(el.closest('.relative.h-full')).not.toBeNull();
      expect(el.classList.contains('absolute')).toBe(true);
      expect(el.classList.contains('rounded-lg')).toBe(true);
      expect(el.classList.contains('fixed')).toBe(false);
      expect(el.classList.contains('left-2')).toBe(true);
      expect(el.classList.contains('md:left-4')).toBe(true);
      expect(el.classList.contains('md:bottom-4')).toBe(true);
    });

    it('associates the move handle with its keyboard movement instructions', () => {
      const f = render();
      const root = bar(f)!;
      const handle = root.querySelector<HTMLElement>('[data-toolbar-drag-handle]')!;
      expect(handle.getAttribute('aria-describedby')).toBe('selection-bar-move-help');
      expect(root.querySelector('#selection-bar-move-help')?.textContent).toContain(I18N.gallery.selection.move_bar_help);
    });

    const S = I18N.gallery.selection;
    const tooltipOf = (f: ComponentFixture<GalleryComponent>, el: Element) =>
      f.debugElement.queryAll(By.directive(MatTooltip)).find(d => d.nativeElement === el)?.injector.get(MatTooltip).message;
    const EDITION_ACTIONS = [
      S.select_all, S.invert, '─',
      I18N.gallery.sidebar.tabs.review, I18N.albums.add_photos, S.mark_sequence, S.edit_metadata, S.download, '─',
      I18N.stacks.create, S.copy_filenames, I18N.export.action, I18N.cull.action, I18N.photo_refresh.title, '─',
      I18N.photo_detail.remove_catalog.action, I18N.cull.delete_action,
    ];
    const SUBMENUS: string[] = [I18N.gallery.sidebar.tabs.review, I18N.albums.add_photos, S.mark_sequence, S.edit_metadata];

    it('keeps Clear, the review decisions and Actions on the bar with matching tooltip and accessible name', () => {
      const f = render();
      for (const key of [S.clear, I18N.review.keep, S.reject, S.actions]) {
        const button = labelled(f, key);
        expect(button, key).not.toBeNull();
        expect(button!.querySelector('mat-icon'), key).not.toBeNull();
        expect(tooltipOf(f, button!), key).toBe(key);
      }
      for (const label of [I18N.review.keep, S.reject]) expect(labelled(f, label)!.textContent).toContain(label);
    });

    it('opens every secondary command from one Actions menu, grouped and divided as approved', () => {
      const f = render();
      const trigger = bar(f)!.querySelector<HTMLButtonElement>('[data-selection-more]')!;
      expect(trigger.textContent).toContain(S.actions);
      expect(trigger.querySelector('mat-icon')!.textContent).toBe('more_horiz');
      expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
      for (const label of [S.favorite, S.edit_tags, S.copy_filenames, I18N.cull.delete_action]) {
        expect(labelled(f, label), label).toBeNull();
        expect(bar(f)!.textContent, label).not.toContain(label);
      }
      const actions = openSelectionActions(f);
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      expect(menuEntries(actions)).toEqual(EDITION_ACTIONS);
      for (const item of actions.querySelectorAll('.mat-mdc-menu-item')) {
        const label = menuItemLabel(item);
        expect(item.querySelector('mat-icon'), label).not.toBeNull();
        expect(item.getAttribute('aria-haspopup'), label).toBe(SUBMENUS.includes(label) ? 'menu' : null);
      }
    });

    it('gives a viewer without edition only selection, download and copy', () => {
      expect(menuEntries(openSelectionActions(render({ edition: false }))))
        .toEqual([S.select_all, S.invert, '─', S.download, '─', S.copy_filenames]);
    });

    it('drops Select all once every loaded photo is selected', () => {
      mockStore.photos.set([makePhoto({ path: '/a.jpg' }), makePhoto({ path: '/b.jpg' })]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      expect(menuEntries(openSelectionActions(render())).slice(0, 2)).toEqual([S.invert, '─']);
    });

    it('nests favorite, reset decision and the 1-5 star ratings under Review, each named for assistive technology', async () => {
      const f = render();
      const rate = vi.spyOn(f.componentInstance.selectionActions, 'batchRate').mockResolvedValue(undefined);
      const review = openSelectionSubmenu(f, openSelectionActions(f), I18N.gallery.sidebar.tabs.review);
      expect(openMenuPanels()).toHaveLength(2);
      expect(menuEntries(review)).toEqual([S.favorite, I18N.review.reset, '─', '★', '★★', '★★★', '★★★★', '★★★★★', S.clear_rating]);
      const stars = [...review.querySelectorAll('.mat-mdc-menu-item')].slice(2, 7);
      expect(stars.map(item => item.getAttribute('aria-label'))).toEqual([1, 2, 3, 4, 5].map(star => `${S.rate} ${star}`));
      expect([...review.querySelectorAll('.mat-mdc-menu-item')].every(item => !item.hasAttribute('aria-haspopup'))).toBe(true);
      menuItem(review, '★★★')!.click();
      f.detectChanges();
      expect(rate).toHaveBeenCalledWith(3);
      await settle();
      expect(openMenuPanels()).toHaveLength(0);
    });

    it('lists the albums and New album under Add to album, and leaves the entry out when albums are off', async () => {
      (TestBed.inject(AlbumService).list as Mock).mockReturnValue(of({ albums: [{ id: 7, name: 'Trip' }] }));
      const f = render();
      await f.whenStable();
      const add = vi.spyOn(f.componentInstance.selectionActions, 'addToAlbum').mockResolvedValue(undefined);
      const albums = openSelectionSubmenu(f, openSelectionActions(f), I18N.albums.add_photos);
      expect(menuEntries(albums)).toEqual(['Trip', I18N.albums.create]);
      menuItem(albums, 'Trip')!.click();
      expect(add).toHaveBeenCalledWith(7);
      f.destroy();
      expect(menuEntries(openSelectionActions(render({ albums: false })))).toEqual(EDITION_ACTIONS.filter(entry => entry !== I18N.albums.add_photos));
    });

    it('nests the three set kinds under Mark as a set', () => {
      const f = render();
      const mark = vi.spyOn(f.componentInstance.selectionActions, 'markAsPanorama').mockResolvedValue(undefined);
      const sets = openSelectionSubmenu(f, openSelectionActions(f), S.mark_sequence);
      expect(menuEntries(sets)).toEqual([S.mark_panorama, S.mark_hdr_panorama, S.mark_bracket]);
      menuItem(sets, S.mark_bracket)!.click();
      expect(mark).toHaveBeenCalledWith('bracket');
    });

    it('nests capture date, location and tags under Edit metadata', () => {
      const f = render();
      const inst = f.componentInstance.selectionActions;
      const date = vi.spyOn(inst, 'openCaptureDateDialog').mockResolvedValue(undefined);
      const gps = vi.spyOn(inst, 'openBatchGpsDialog').mockResolvedValue(undefined);
      const tags = vi.spyOn(inst, 'openManualTagsDialog').mockResolvedValue(undefined);
      const metadata = openSelectionSubmenu(f, openSelectionActions(f), S.edit_metadata);
      expect(menuEntries(metadata)).toEqual([I18N.capture_date.title, I18N.photo_detail.gps.batch_title, S.edit_tags]);
      menuItem(metadata, I18N.photo_detail.gps.batch_title)!.click();
      expect(gps).toHaveBeenCalledTimes(1);
      expect(date).not.toHaveBeenCalled();
      expect(tags).not.toHaveBeenCalled();
    });

    it('offers the download types in a submenu only when darktable profiles exist', () => {
      const plain = render();
      const original = vi.spyOn(plain.componentInstance.selectionActions, 'downloadSelected').mockResolvedValue(undefined);
      const item = menuItem(openSelectionActions(plain), S.download)!;
      expect(item.getAttribute('aria-haspopup')).toBeNull();
      item.click();
      expect(original).toHaveBeenCalledWith();
      plain.destroy();
      const f = render({ profiles: ['web'] });
      const typed = vi.spyOn(f.componentInstance.selectionActions, 'downloadSelected').mockResolvedValue(undefined);
      const types = openSelectionSubmenu(f, openSelectionActions(f), S.download);
      expect(menuEntries(types)).toEqual([I18N.download.type_original, 'web', I18N.download.type_raw]);
      menuItem(types, 'web')!.click();
      expect(typed).toHaveBeenCalledWith('darktable', 'web');
    });

    it('leaves Delete out without a trash, keeping Remove from catalog after its divider', () => {
      expect(menuEntries(openSelectionActions(render({ trash: false }))).slice(-3))
        .toEqual([I18N.photo_refresh.title, '─', I18N.photo_detail.remove_catalog.action]);
    });

    it('keeps the commands a whole-view selection cannot drive focusable but inert, each stating why', () => {
      const f = render({ viewScoped: true });
      const actions = openSelectionActions(f);
      const photoActions = TestBed.inject(PhotoActionsService);
      const refresh = vi.spyOn(photoActions, 'refreshPhotos');
      const remove = vi.spyOn(photoActions, 'removeFromCatalog');
      const reasons: [string, string][] = [
        [I18N.stacks.create, I18N.stacks.explicit_only],
        [I18N.photo_refresh.title, S.explicit_required],
        [I18N.photo_detail.remove_catalog.action, S.explicit_required],
        [I18N.cull.delete_action, I18N.cull.delete_disabled_view_scope_tooltip],
      ];
      for (const [label, why] of reasons) {
        const item = menuItem(actions, label)!;
        expect(item.disabled, label).toBe(false);
        expect(item.getAttribute('aria-disabled'), label).toBe('true');
        expect(tooltipOf(f, item), label).toBe(why);
        item.click();
        f.detectChanges();
      }
      expect(refresh).not.toHaveBeenCalled();
      expect(remove).not.toHaveBeenCalled();
      expect(TestBed.inject(MatDialog).open).not.toHaveBeenCalled();
      expect(openMenuPanels()).toHaveLength(1);
    });

    it('states the refresh limit when the selection is too large to refresh', () => {
      const f = render();
      mockStore.selectionCount.set(MAX_REFRESH_PATHS + 1);
      f.detectChanges();
      const actions = openSelectionActions(f);
      const refresh = menuItem(actions, I18N.photo_refresh.title)!;
      expect(refresh.getAttribute('aria-disabled')).toBe('true');
      expect(tooltipOf(f, refresh)).toBe(I18N.photo_refresh.limit);
      for (const label of [I18N.stacks.create, I18N.photo_detail.remove_catalog.action, I18N.cull.delete_action]) {
        expect(menuItem(actions, label)!.getAttribute('aria-disabled'), label).toBeNull();
      }
      expect(tooltipOf(f, menuItem(actions, I18N.cull.delete_action)!)).toBeFalsy();
    });

    it('walks into a submenu and back out with the keyboard, keeping the selection', async () => {
      const f = render();
      const trigger = bar(f)!.querySelector<HTMLButtonElement>('[data-selection-more]')!;
      const actions = openSelectionActions(f);
      const review = menuItem(actions, I18N.gallery.sidebar.tabs.review)!;
      review.focus();
      keydown(review, 'ArrowRight', 39);
      f.detectChanges();
      expect(openMenuPanels()).toHaveLength(2);
      const escape = keydown(openMenuPanels()[1], 'Escape', 27);
      f.detectChanges();
      expect(escape.defaultPrevented).toBe(true);
      expect(document.activeElement).toBe(review);
      await settle();
      expect(openMenuPanels()).toHaveLength(1);
      keydown(actions, 'Escape', 27);
      f.detectChanges();
      await settle();
      expect(openMenuPanels()).toHaveLength(0);
      expect(document.activeElement).toBe(trigger);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('keeps the Compare requirement out of the flow and on the Compare tooltip', () => {
      const f = render({ viewScoped: true });
      const requirement = bar(f)!.querySelector<HTMLElement>('#compare-selection-requirements')!;
      expect(requirement.classList.contains('sr-only')).toBe(true);
      expect(requirement.classList.contains('basis-full')).toBe(false);
      const compare = labelled(f, I18N.gallery.selection.compare)!;
      expect(compare.getAttribute('aria-describedby')).toBe('compare-selection-requirements');
      const tooltip = f.debugElement.queryAll(By.directive(MatTooltip)).find(d => d.nativeElement === compare);
      expect(tooltip?.injector.get(MatTooltip).message).toBe(requirement.textContent!.trim());
    });

    it('keeps the disabled Compare button focusable so keyboard users reach the reason, and a click does nothing', () => {
      const f = render({ viewScoped: true });
      const compare = labelled(f, I18N.gallery.selection.compare)!;
      expect(compare.disabled).toBe(false);
      expect(compare.getAttribute('aria-disabled')).toBe('true');
      expect(compare.getAttribute('aria-describedby')).toBe('compare-selection-requirements');
      compare.focus();
      expect(document.activeElement).toBe(compare);
      const start = vi.spyOn(TestBed.inject(ComparisonSessionService), 'start');
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
      compare.click();
      expect(start).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('closes the whole menu once a command runs, and with the bar when the selection goes', async () => {
      const f = render();
      const copy = vi.spyOn(f.componentInstance.selectionActions, 'copyPaths').mockResolvedValue(undefined);
      menuItem(openSelectionActions(f), S.copy_filenames)!.click();
      f.detectChanges();
      expect(copy).toHaveBeenCalledTimes(1);
      await settle();
      expect(openMenuPanels()).toHaveLength(0);
      openSelectionActions(f);
      expect(openMenuPanels()).toHaveLength(1);
      mockStore.selectionCount.set(0);
      f.detectChanges();
      expect(bar(f)).toBeNull();
      expect(openMenuPanels()).toHaveLength(0);
    });

    it('closes the Targets disclosure when the Actions menu opens', () => {
      const f = render({ viewScoped: true });
      const targets = bar(f)!.querySelector<HTMLDetailsElement>('[data-selection-targets]')!;
      targets.open = true;
      openSelectionActions(f);
      expect(targets.open).toBe(false);
    });

    it('uses an icon present in the shipped font for Cull to folder', () => {
      const f = render();
      expect(menuItem(openSelectionActions(f), I18N.cull.action)!.querySelector('mat-icon')!.textContent).toBe('move_to_inbox');
    });

    it('keeps the tooltip on the disabled delete entry (disabledInteractive)', () => {
      const f = render({ viewScoped: true });
      const del = menuItem(openSelectionActions(f), I18N.cull.delete_action)!;
      expect(del.getAttribute('aria-disabled')).toBe('true');
      expect(del.disabled).toBe(false);
    });

    // disabledInteractive leaves a <button> clickable, so these must stay natively
    // disabled or a click mid-download starts a second download.
    it('natively disables every download entry point while a download runs', () => {
      for (const profiles of [[], ['web']]) {
        const f = render({ profiles });
        f.componentInstance.selectionActions.downloading.set(true);
        f.detectChanges();
        const download = menuItem(openSelectionActions(f), I18N.photo_detail.downloading)!;
        expect(download.disabled).toBe(true);
        expect(download.querySelector('mat-spinner')).not.toBeNull();
        expect(labelled(f, I18N.gallery.selection.actions)!.disabled).toBe(true);
        f.destroy();
      }
    });

    it('uses the view-scope text as the delete tooltip when the selection is the whole view', () => {
      const f = render({ viewScoped: true });
      const del = menuItem(openSelectionActions(f), I18N.cull.delete_action)!;
      expect(tooltipOf(f, del)).toBe(I18N.cull.delete_disabled_view_scope_tooltip);
    });

    it('hides the desktop Actions trigger below md and keeps one phone Actions button', () => {
      const f = render();
      expect(bar(f)!.querySelector('[data-selection-more]')!.classList.contains('max-md:hidden')).toBe(true);
      expect(labelled(f, I18N.gallery.selection.actions)!.classList.contains('md:!hidden')).toBe(true);
    });

    it('opens the actions sheet from the Actions button', () => {
      const f = render({ desktop: false });
      const open = vi.spyOn(f.componentInstance as unknown as { openActionsSheet(): Promise<void> }, 'openActionsSheet').mockResolvedValue(undefined);
      labelled(f, I18N.gallery.selection.actions)!.click();
      expect(open).toHaveBeenCalledTimes(1);
    });

    it('calls the same handlers as before for favorite, reject and copy', async () => {
      const f = render();
      const inst = f.componentInstance.selectionActions;
      const fav = vi.spyOn(inst, 'batchFavorite').mockResolvedValue(undefined);
      const rej = vi.spyOn(inst, 'batchReject').mockResolvedValue(undefined);
      const copy = vi.spyOn(inst, 'copyPaths').mockResolvedValue(undefined);
      labelled(f, I18N.gallery.selection.reject)!.click();
      menuItem(openSelectionSubmenu(f, openSelectionActions(f), I18N.gallery.sidebar.tabs.review), S.favorite)!.click();
      f.detectChanges();
      await settle();
      menuItem(openSelectionActions(f), S.copy_filenames)!.click();
      expect(fav).toHaveBeenCalled();
      expect(rej).toHaveBeenCalled();
      expect(copy).toHaveBeenCalled();
    });

    it('hides while the mobile over drawer is open and returns when it closes, keeping the selection', () => {
      const f = render({ desktop: false });
      mockStore.filterDrawerOpen.set(true);
      f.detectChanges();
      expect(bar(f)).toBeNull();
      expect(mockStore.selectionCount()).toBe(2);
      mockStore.filterDrawerOpen.set(false);
      f.detectChanges();
      expect(bar(f)).not.toBeNull();
    });

    describe('notice baseline and end spacer', () => {
      const rect = (left: number, right: number, top: number, bottom: number) =>
        ({ left, right, top, bottom, width: right - left, height: bottom - top, x: left, y: top, toJSON() { return {}; } }) as DOMRect;

      function mockLayout(barRight: number, barTop: number) {
        vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
        const original = HTMLElement.prototype.getBoundingClientRect;
        vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
          if (this.classList.contains('relative') && this.classList.contains('h-full')) return rect(0, 1200, 0, 800);
          if (this.hasAttribute('data-selection-bar')) return rect(16, barRight, barTop, 784);
          if (this.hasAttribute('data-gallery-notices')) return rect(768, 1184, 600, 700);
          return original.call(this);
        });
        mockStore.hiddenSummary.set({ total: 6, blinks: 0, bursts: 4, duplicates: 0, brackets: 2, panoramas: 0 });
        mockStore.filters.set({ ...DEFAULT_FILTERS, hide_bursts: true });
      }

      const noticeBottom = (f: ComponentFixture<GalleryComponent>) => (f.componentInstance as unknown as { noticeBottomPx(): number }).noticeBottomPx();

      it('rests the notices on the 16px desktop margin when the card is narrow', () => {
        mockLayout(300, 740);
        const f = render();
        f.detectChanges();
        expect(noticeBottom(f)).toBe(16);
      });

      it('lifts the notices by the card reach when a wide card overlaps them', () => {
        mockLayout(1000, 740);
        const f = render();
        f.detectChanges();
        expect(noticeBottom(f)).toBe(16 + (800 - 740));
      });

      it('sizes the end spacer from the measured reach, never below 112px', () => {
        mockLayout(1000, 640);
        const f = render();
        f.detectChanges();
        const spacer = f.nativeElement.querySelector('mat-sidenav-content div[aria-hidden="true"][style*="height"]') as HTMLElement;
        expect(spacer.style.height).toBe('160px');
      });

      it('uses the 8px margin on mobile and 16px on desktop with no selection', () => {
        mockStore.selectionCount.set(0);
        const desktop = render();
        expect(noticeBottom(desktop)).toBe(16);
        desktop.destroy();
        const mobile = render({ desktop: false });
        mockStore.selectionCount.set(0);
        mobile.detectChanges();
        expect(noticeBottom(mobile)).toBe(8);
      });
    });
  });

  describe('openActionsSheet -> delete dispatch (mobile)', () => {
    beforeEach(() => {
      mockAuth['downloadProfiles'] = vi.fn(() => []);
    });

    it('passes trashAvailable through to the sheet data', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock).mockReturnValue({ afterDismissed: () => of(null) });

      await (component as unknown as { openActionsSheet(): Promise<void> }).openActionsSheet();

      const data = (bottomSheet.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(true);
    });

    it('tells the sheet whether Select all applies and dispatches its Select all and Remove from catalog', async () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock)
        .mockReturnValueOnce({ afterDismissed: () => of({ kind: 'select-all' }) })
        .mockReturnValueOnce({ afterDismissed: () => of({ kind: 'remove-catalog' }) });
      const remove = vi.spyOn(component.selectionActions, 'removeSelectedFromCatalog').mockResolvedValue();
      const open = () => (component as unknown as { openActionsSheet(): Promise<void> }).openActionsSheet();

      await open();
      expect((bottomSheet.open as Mock).mock.calls[0][1].data.canSelectAll).toBe(true);
      expect(mockStore.selectAll).toHaveBeenCalledTimes(1);
      await open();
      expect(remove).toHaveBeenCalledTimes(1);
    });

    it('dispatches to deleteSelected() when the sheet resolves { kind: "delete" }', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock).mockReturnValue({ afterDismissed: () => of({ kind: 'delete' }) });
      const spy = vi.spyOn(component.selectionActions, 'deleteSelected').mockResolvedValue();

      await (component as unknown as { openActionsSheet(): Promise<void> }).openActionsSheet();

      expect(spy).toHaveBeenCalled();
    });
  });

  describe('openExportDialog', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    it('opens the album-scoped dialog when the route carries an albumId, ignoring selection scope', () => {
      routeMock.snapshot.paramMap.get = vi.fn(() => '42');
      const dialog = TestBed.inject(MatDialog);

      component.selectionActions.openExportDialog();

      expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
    });

    it('sends the filter payload, exclude list and count under view scope, with no paths key', () => {
      mockStore.selectionScope.set('view');
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);

      component.selectionActions.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ filters: { page: '1' }, exclude: ['/skip.jpg'], count: 650 });
      expect(data.paths).toBeUndefined();
    });

    it('sends the selected paths under path scope, with no filters key', () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);

      component.selectionActions.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ paths: ['/a.jpg', '/b.jpg'] });
      expect(data.filters).toBeUndefined();
    });
  });

  describe('selection target disclosure', () => {
    it('shows permitted matching stack counts and other group kinds without widening selection', () => {
      const grouped = makePhoto({ path: '/a.jpg', stack_id: 'manual', stack_count: 2, stack_total_count: 4, sequence_kind: 'bracket', sequence_group_id: 0, burst_group_id: 0 });
      mockStore.photos.set([grouped]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/offscreen.jpg']));
      mockStore.selectionCount.set(2);
      vi.mocked(TestBed.inject(I18nService).t).mockImplementation((key, vars) => key + (vars ? JSON.stringify(vars) : ''));
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      const disclosure = root.querySelector<HTMLDetailsElement>('[data-selection-targets]')!;
      expect(disclosure.textContent).toContain('gallery.selection.targets.explicit');
      expect(disclosure.textContent).toContain('"matching":2,"total":4');
      expect(disclosure.textContent).toContain('gallery.selection.targets.manual');
      expect(disclosure.textContent).toContain('culling.type_burst');
      expect([...mockStore.selectedPaths()]).toEqual(['/a.jpg', '/offscreen.jpg']);
      disclosure.open = true;
      disclosure.querySelector('summary')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      expect(disclosure.open).toBe(false);
      expect([...mockStore.selectedPaths()]).toEqual(['/a.jpg', '/offscreen.jpg']);
      expect(TestBed.inject(ApiService).post).not.toHaveBeenCalled();
      fixture.destroy();
    });

    it('describes whole-view matching membership without presenting tile observations as the whole target', () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionCount.set(40);
      mockStore.photos.set([makePhoto({ path: '/a.jpg', stack_id: 'manual', stack_count: 2, stack_total_count: 4 })]);
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const disclosure = (fixture.nativeElement as HTMLElement).querySelector('[data-selection-targets]')!;
      expect(disclosure.textContent).toContain('gallery.selection.targets.view');
      expect(disclosure.textContent).not.toContain('gallery.selection.targets.stack_count');
      fixture.destroy();
    });
  });

  describe('whole-view selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const offered = () => (component as unknown as { offerWholeView: () => boolean }).offerWholeView();

    describe('the banner offering to widen the selection', () => {
      beforeEach(() => {
        mockStore.photos.set(['/a.jpg', '/b.jpg'].map(photo));
        mockStore.total.set(650);
        select(['/a.jpg', '/b.jpg']);
      });

      it('shows when every loaded photo is selected and the view holds more', () => {
        expect(offered()).toBe(true);
      });

      it('does not mistake folded selected members for selection of every displayed tile', () => {
        mockStore.photos.set(['/cover.jpg', '/unstacked.jpg'].map(photo));
        select(['/cover.jpg', '/folded-one.jpg', '/folded-two.jpg']);
        expect(offered()).toBe(false);
        expect((component as unknown as { allLoadedSelected: () => boolean }).allLoadedSelected()).toBe(false);
      });

      it('checks loaded exclusions in a whole-view selection', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(649);
        mockStore.excludedPaths.set(new Set(['/b.jpg']));
        expect((component as unknown as { allLoadedSelected: () => boolean }).allLoadedSelected()).toBe(false);
        mockStore.excludedPaths.set(new Set(['/outside-loaded.jpg']));
        expect((component as unknown as { allLoadedSelected: () => boolean }).allLoadedSelected()).toBe(true);
      });

      it('stays hidden while only part of the loaded page is selected', () => {
        select(['/a.jpg']);
        expect(offered()).toBe(false);
      });

      it('stays hidden when the loaded page IS the whole view — nothing to widen to', () => {
        mockStore.total.set(2);
        expect(offered()).toBe(false);
      });

      it('stays hidden once the selection is already the whole view', () => {
        mockStore.viewScopeSelected.set(true);
        expect(offered()).toBe(false);
      });

      it('stays hidden under a view with no filter form to widen into', () => {
        mockStore.canScopeSelectionToView.set(false);
        expect(offered()).toBe(false);
      });
    });

    // Both "select all in view" and its sibling "select all" render inside an
    // @if keyed on the very selection state their own click flips, so Angular
    // removes the still-focused button on the same tick that the click
    // handler runs. Without focus restoration the browser drops focus to
    // document.body and announces nothing.
    describe('focus and announcement when a toggle button removes itself', () => {
      let liveAnnouncer: { announce: Mock };
      let statusEl: HTMLElement;
      let vanishingButton: HTMLElement;

      beforeEach(() => {
        liveAnnouncer = TestBed.inject(LiveAnnouncer) as unknown as { announce: Mock };
        // Stand-ins for the real template markup: the always-rendered status
        // span the fix anchors focus to, and the button the click originated
        // from -- which the real @if would remove right after.
        statusEl = document.createElement('span');
        statusEl.setAttribute('data-selection-status', '');
        statusEl.tabIndex = -1;
        document.body.appendChild(statusEl);
        vanishingButton = document.createElement('button');
        document.body.appendChild(vanishingButton);
        vanishingButton.focus();
      });

      afterEach(() => {
        statusEl.remove();
        vanishingButton.remove();
      });

      it('moves focus off the "select all in view" button onto the status text', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(650);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { selectWholeView: () => void }).selectWholeView();

        expect(document.activeElement).toBe(statusEl);
        expect(document.activeElement).not.toBe(document.body);
      });


      it('announces the new whole-view selection state', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(650);

        (component as unknown as { selectWholeView: () => void }).selectWholeView();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.view_scope_active');
      });

      it('names the exclusions when the whole view is selected minus some photos', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(648);
        mockStore.excludedPaths.set(new Set(['/a.jpg', '/b.jpg']));

        (component as unknown as { selectWholeView: () => void }).selectWholeView();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.view_scope_except');
      });

      it('moves focus off the sibling "select all" button onto the status text', () => {
        mockStore.selectionCount.set(2);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { selectAll: () => void }).selectAll();

        expect(document.activeElement).toBe(statusEl);
        expect(document.activeElement).not.toBe(document.body);
      });

      it('announces the new selection count from the sibling "select all" button', () => {
        mockStore.selectionCount.set(2);

        (component as unknown as { selectAll: () => void }).selectAll();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.count');
      });

      it('announces the new count when the selection is inverted', () => {
        mockStore.selectionCount.set(7);

        (component as unknown as { invertSelection: () => void }).invertSelection();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.count');
      });

      it('leaves focus on the invert button, which survives its own click', () => {
        mockStore.selectionCount.set(7);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { invertSelection: () => void }).invertSelection();

        expect(document.activeElement).toBe(vanishingButton);
        expect(document.activeElement).not.toBe(statusEl);
      });
    });

    describe('confirming a mutation that runs over the whole view', () => {
      let dialog: MatDialog;
      let snackOpen: Mock;

      beforeEach(() => {
        mockAuth['isEdition'] = vi.fn(() => true);
        mockStore.photos.set(['/a.jpg', '/b.jpg'].map(photo));
        mockStore.total.set(650);
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionScope.set('view');
        mockStore.selectionCount.set(650);
        dialog = TestBed.inject(MatDialog);
        snackOpen = TestBed.inject(MatSnackBar).open as Mock;
      });

      const favorite = () =>
        component.selectionActions.batchFavorite();

      it('counts the view from the server, then asks, before writing anything', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await favorite();

        expect(mockStore.countInView).toHaveBeenCalled();
        expect(dialog.open).toHaveBeenCalled();
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_confirm_message');
        expect(mockStore.batchFavorite).toHaveBeenCalled();
      });

      it('writes nothing when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await favorite();

        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      it.each(['exclusions', 'criteria'] as const)('refuses changed %s while the target count is pending', async change => {
        let resolve!: (count: number) => void;
        mockStore.countInView.mockReturnValue(new Promise<number>(done => { resolve = done; }));
        mockStore.filterPayload = vi.fn(() => ({ tag: mockStore.filters().tag }));
        const pending = favorite();
        if (change === 'exclusions') mockStore.excludedPaths.set(new Set(['/a.jpg']));
        else mockStore.filters.update((filters: GalleryFilters) => ({ ...filters, tag: 'new' }));
        resolve(650); await pending;
        expect(dialog.open).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      it.each(['selection', 'edition', 'navigation'] as const)('refuses changed %s after the confirmation opened', async change => {
        const closed = new Subject<boolean>();
        let didOpen!: () => void;
        const opened = new Promise<void>(resolve => { didOpen = resolve; });
        (dialog.open as Mock).mockImplementation(() => { didOpen(); return { afterClosed: () => closed }; });
        const pending = favorite(); await opened;
        if (change === 'selection') {
          mockStore.viewScopeSelected.set(false);
          mockStore.selectedPaths.set(new Set(['/new.jpg']));
        } else if (change === 'edition') mockAuth['isEdition'] = vi.fn(() => false);
        else {
          const router = TestBed.inject(Router);
          router.resetConfig([{ path: 'photo', component: MenuPhotoRoute }]);
          await router.navigateByUrl('/photo?path=%2Fa.jpg');
        }
        closed.next(true); await pending;
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      it('retains a newer explicit selection after the accepted batch finishes', async () => {
        mockStore.viewScopeSelected.set(false);
        mockStore.selectedPaths.set(new Set(['/a.jpg']));
        let resolve!: (result: unknown) => void;
        mockStore.batchFavorite.mockReturnValue(new Promise(done => { resolve = done; }));
        const pending = favorite();
        expect(mockStore.batchFavorite).toHaveBeenCalledWith(['/a.jpg']);
        mockStore.selectedPaths.set(new Set(['/b.jpg']));
        resolve({ snapshot: new Map(), targeted: 1, count: 1 }); await pending;
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect([...mockStore.selectedPaths()]).toEqual(['/b.jpg']);
      });

      it('writes nothing when the count cannot be fetched', async () => {
        mockStore.countInView.mockResolvedValue(null);

        await favorite();

        expect(dialog.open).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      // The server total minus what the user unticked can land on zero — the
      // whole view was already excluded down to nothing. That must short-
      // circuit before the confirm dialog, not open it to confirm acting on 0.
      it('tells the user there is nothing to act on when exclusions cover the whole view', async () => {
        mockStore.excludedPaths.set(new Set(['/a.jpg', '/b.jpg']));
        mockStore.countInView.mockResolvedValue(2);

        await favorite();

        expect(dialog.open).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_empty')).toBe(true);
      });

      // The user approved a number; if the view moved under the write, say so
      // rather than quietly reporting whatever happened.
      it('reports a server count that disagrees with the number confirmed', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
        mockStore.countInView.mockResolvedValue(650);
        mockStore.batchFavorite.mockResolvedValue({ snapshot: new Map(), targeted: 650, count: 640 });

        await favorite();

        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_mismatch')).toBe(true);
      });

      it('says nothing when the server changed exactly what was confirmed', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
        mockStore.countInView.mockResolvedValue(650);
        mockStore.batchFavorite.mockResolvedValue({ snapshot: new Map(), targeted: 650, count: 650 });

        await favorite();

        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_mismatch')).toBe(false);
      });
    });

    it('refuses to declare a whole view one panorama', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionCount.set(650);

      await component.selectionActions
        .markAsPanorama('panorama');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('undo is only offered when it would restore everything', () => {
    const snap = { is_favorite: false, is_rejected: false, star_rating: null };
    let undoRegister: Mock;
    let snackOpen: Mock;

    beforeEach(() => {
      mockAuth['isEdition'] = vi.fn(() => true);
      undoRegister = vi.fn();
      vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(undoRegister);
      snackOpen = TestBed.inject(MatSnackBar).open as Mock;
    });

    const reject = () => component.selectionActions.batchReject();

    it.each(['kept', 'undecided'] as const)('offers Undo for a single %s decision without changing selection', async decision => {
      const snapshot = new Map([['/a.jpg', { ...snap, is_kept: false }]]);
      mockStore.batchReview = vi.fn().mockResolvedValue({ snapshot, targeted: 1, count: 1 });
      mockStore.restoreSnapshot.mockResolvedValue(undefined);
      await component.selectionActions.reviewSingle('/a.jpg', decision);
      expect(mockStore.batchReview).toHaveBeenCalledWith(['/a.jpg'], decision, false);
      expect(undoRegister).toHaveBeenCalledWith(expect.objectContaining({ labelKey: 'review.updated', labelParams: { count: 1 } }));
      await undoRegister.mock.calls[0][0].undo();
      expect(mockStore.restoreSnapshot).toHaveBeenCalledWith(snapshot);
      expect(mockStore.restoreSelection).not.toHaveBeenCalled();
    });

    it('offers undo when the snapshot covers every photo the action touched', async () => {
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      mockStore.selectionCount.set(2);
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map([['/a.jpg', snap], ['/b.jpg', snap]]), targeted: 2, count: 2,
      });

      await reject();

      expect(undoRegister).toHaveBeenCalled();
    });

    // The snapshot is built from the LOADED photos, so a 5,000-path selection
    // (from "Keep top N%") yields a ~64-entry one: small enough to pass the
    // UNDO_MAX_PHOTOS gate, and an "undo" that would restore 64 of 5,000.
    it('withholds undo when the snapshot covers only the loaded page of a much larger action', async () => {
      const paths = Array.from({ length: 5000 }, (_, i) => `/p${i}.jpg`);
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map(paths.slice(0, 64).map(path => [path, snap])),
        targeted: 5000,
        count: 5000,
      });

      await reject();

      expect(undoRegister).not.toHaveBeenCalled();
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.batch_rejected')).toBe(true);
    });

    it('withholds undo for a whole-view action, whose snapshot can never cover it', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      (TestBed.inject(MatDialog).open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map([['/a.jpg', snap]]), targeted: 650, count: 650,
      });

      await reject();

      expect(undoRegister).not.toHaveBeenCalled();
    });
  });

  describe('marking a selection as one panorama', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const mark = (kind: SequenceKind = 'panorama') =>
      component.selectionActions.markAsPanorama(kind);

    // The gallery is the only surface that can correct a MISS: an undetected
    // sweep is in no culling group, so it can only be named where its frames
    // are visible as ordinary photos.
    it('sends every selected path with the chosen kind', async () => {
      select(['/a.jpg', '/b.jpg', '/c.jpg']);

      await mark('hdr_panorama');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/a.jpg', '/b.jpg', '/c.jpg'],
        kind: 'hdr_panorama',
      });
    });

    it('marks the photos pending and clears the selection', async () => {
      select(['/a.jpg', '/b.jpg']);

      await mark();

      expect(mockStore.patchSequenceOverride).toHaveBeenCalledWith(['/a.jpg', '/b.jpg'], 'panorama');
      expect(mockStore.clearSelection).toHaveBeenCalled();
    });

    it('refuses a single photo — one frame is not a set', async () => {
      select(['/a.jpg']);

      await mark();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    // The server caps a sequence correction at MARK_SEQUENCE_MAX_PHOTOS (500)
    // frames; a set is a handful of frames one camera shot together, never
    // hundreds, so this refusal is client-side, before any request is sent.
    it('refuses more paths than the server-side correction cap', async () => {
      const paths = Array.from({ length: 501 }, (_, i) => `/p${i}.jpg`);
      select(paths);
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark();

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(mockStore.patchSequenceOverride).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.mark_too_many')).toBe(true);
    });

    it('marks nothing when the server refuses', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('nope')));

      await mark();

      expect(mockStore.patchSequenceOverride).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('sends kind: bracket and uses the bracket-worded undo label', async () => {
      const undoRegister = vi.fn();
      vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(undoRegister);
      select(['/a.jpg', '/b.jpg']);

      await mark('bracket');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/a.jpg', '/b.jpg'],
        kind: 'bracket',
      });
      expect(undoRegister).toHaveBeenCalledWith(
        expect.objectContaining({ labelKey: 'gallery.selection.marked_bracket' }));
    });

    it('shows the ladder-specific message when a bracket mark 400s', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark('bracket');

      expect(snackOpen.mock.calls.some(c => c[0] === 'culling.bracket.not_a_ladder')).toBe(true);
    });

    it('keeps the generic error for a non-bracket 400', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark('panorama');

      expect(snackOpen.mock.calls.some(c => c[0] === 'errors.action_failed')).toBe(true);
      expect(snackOpen.mock.calls.some(c => c[0] === 'culling.bracket.not_a_ladder')).toBe(false);
    });
  });

  describe('downloadSelected', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const download = () =>
      component.selectionActions.downloadSelected();

    // Past DOWNLOAD_CONFIRM_PHOTOS (50), a download is one blob fetch plus one
    // synthetic anchor click PER PHOTO, serially -- confirm before starting
    // something that size by accident.
    it('asks for confirmation before downloading more than DOWNLOAD_CONFIRM_PHOTOS photos', async () => {
      select(Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

      await download();

      expect(dialog.open).toHaveBeenCalled();
      expect((dialog.open as Mock).mock.calls[0][1].data.message)
        .toBe('gallery.selection.download_confirm_message');
      expect(mockApi.getRaw).not.toHaveBeenCalled();
    });

    it('downloads once an oversized selection is confirmed', async () => {
      select(Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

      await download();

      expect(mockApi.getRaw).toHaveBeenCalled();
    });

    it('downloads without confirming at or under the limit', async () => {
      select(Array.from({ length: 50 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);

      await download();

      expect(dialog.open).not.toHaveBeenCalled();
      expect(mockApi.getRaw).toHaveBeenCalled();
    });
  });

  // Under a whole-view selection these three actions read no local selection at
  // all: they ask the server for the paths, which can resolve to null — a
  // refusal past the endpoint's cap, a failed request, or a declined
  // confirmation. A swapped condition or a dropped null check would turn all
  // three into silent no-ops with the rest of the suite still green.
  describe('actions that resolve a whole-view selection to paths', () => {
    let dialog: MatDialog;
    let addPhotos: Mock;
    let writeText: Mock;
    let clipboardDescriptor: PropertyDescriptor | undefined;

    beforeEach(() => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      mockStore.total.set(650);
      mockStore.pathsInView.mockResolvedValue(['/x.jpg', '/y.jpg']);
      dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      addPhotos = TestBed.inject(AlbumService).addPhotos as unknown as Mock;
      writeText = vi.fn(() => Promise.resolve());
      clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });

    // The stub is a global: left in place it outlives this describe and hands a
    // fake clipboard to every test appended after it.
    afterEach(() => {
      if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
      else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    });

    const copy = () => component.selectionActions.copyPaths();
    const download = () =>
      component.selectionActions.downloadSelected();
    const addToAlbum = () => component.selectionActions.addToAlbum(3);

    describe('copy filenames', () => {
      it('copies the paths the server resolved, not the empty local selection', async () => {
        await copy();

        expect(mockStore.pathsInView).toHaveBeenCalled();
        expect(writeText).toHaveBeenCalledWith('x.jpg\ny.jpg');
      });

      it('copies nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await copy();

        expect(writeText).not.toHaveBeenCalled();
      });

      // Copying changes nothing, so it must not borrow the wording that tells
      // the user their photos are about to be modified.
      it('confirms against the server count, in words that match a copy', async () => {
        await copy();

        expect(mockStore.countInView).toHaveBeenCalled();
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_copy_message');
      });

      it('does not even fetch the paths when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await copy();

        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(writeText).not.toHaveBeenCalled();
      });
    });

    describe('download', () => {
      const fiftyOne = Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`);

      it('downloads the paths the server resolved', async () => {
        await download();

        expect(mockStore.pathsInView).toHaveBeenCalled();
        expect(mockApi.getRaw).toHaveBeenCalled();
      });

      it('downloads nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await download();

        expect(mockApi.getRaw).not.toHaveBeenCalled();
      });

      // The download already confirms in its own words, against the count it
      // actually resolved: two dialogs for one click would be worse than one.
      it('confirms exactly once, with the download wording', async () => {
        mockStore.pathsInView.mockResolvedValue(fiftyOne);

        await download();

        expect((dialog.open as Mock).mock.calls.length).toBe(1);
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.download_confirm_message');
      });

      it('downloads nothing when that confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });
        mockStore.pathsInView.mockResolvedValue(fiftyOne);

        await download();

        expect(mockApi.getRaw).not.toHaveBeenCalled();
      });
    });

    describe('add to album', () => {
      it('adds the paths the server resolved', async () => {
        await addToAlbum();

        expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg', '/y.jpg']);
        expect(mockStore.clearSelection).toHaveBeenCalled();
      });

      it('adds nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await addToAlbum();

        expect(addPhotos).not.toHaveBeenCalled();
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      // Filing photos into an album writes album_photos rows and modifies no
      // photo, so it must not borrow the mutation's wording either.
      it('confirms in the words of filing, not of changing the photos', async () => {
        await addToAlbum();

        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_album_message');
      });

      // One album_photos row per photo in the view, with no undo: the least it
      // can do is ask.
      it('adds nothing when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await addToAlbum();

        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(addPhotos).not.toHaveBeenCalled();
      });
    });
  });

  // The scan entry lives in the shell header (app.html, covered by app.spec.ts); the
  // gallery keeps only the empty-state call to action.
  describe('scan entry (gallery page)', () => {
    const photos = Array.from({ length: 3 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
      is_favorite: false, is_rejected: false, unassigned_faces: 0,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(canLaunch: boolean, library: typeof photos, launched = true) {
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.photos.set(library);
      mockStore.total.set(library.length);
      const scan = TestBed.inject(ScanService) as unknown as { canLaunch: WritableSignal<boolean>; openLauncher: Mock };
      scan.canLaunch.set(canLaunch);
      scan.openLauncher.mockResolvedValue(launched);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return { f: fixture, scan };
    }

    function allButtons(f: ComponentFixture<GalleryComponent>): HTMLButtonElement[] {
      return Array.from(f.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    }

    function getStarted(f: ComponentFixture<GalleryComponent>): HTMLButtonElement[] {
      return allButtons(f).filter(b => b.textContent?.includes(I18N.scan.get_started));
    }

    it('renders no scan button above a populated grid', () => {
      // A locked single-user install with an unlocked edition session, which used to earn the button.
      mockAuth['hasFeature'] = vi.fn(() => true);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['editionPasswordRequired'] = vi.fn(() => true);
      mockAuth['isEdition'] = vi.fn(() => true);
      const { f } = render(true, photos);
      expect(allButtons(f).filter(b => b.getAttribute('aria-label') === I18N.gallery.scan_action)).toHaveLength(0);
      expect(getStarted(f)).toHaveLength(0);
    });

    it('offers the get-started button on an empty, unfiltered library when scanning is allowed', () => {
      expect(getStarted(render(true, []).f)).toHaveLength(1);
    });

    it('withholds the get-started button when scanning is not allowed', () => {
      expect(getStarted(render(false, []).f)).toHaveLength(0);
    });

    it('reloads the counts and the photos when the launcher reports a completed scan', async () => {
      const { f, scan } = render(true, []);
      getStarted(f)[0].click();
      await vi.waitFor(() => expect(mockStore.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(scan.openLauncher).toHaveBeenCalledTimes(1);
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('reloads nothing when the launcher is dismissed', async () => {
      const { f, scan } = render(true, [], false);
      await f.whenStable();
      mockStore.loadTypeCounts.mockClear();
      mockStore.reloadPhotos.mockClear();
      getStarted(f)[0].click();
      await vi.waitFor(() => expect(scan.openLauncher).toHaveBeenCalledTimes(1));
      await f.whenStable();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
      expect(mockStore.reloadPhotos).not.toHaveBeenCalled();
    });
  });

  // The gallery's right-click menu acts on explicit paths: the menu's single-photo
  // actions must reach these methods without resolving, confirming over or
  // clearing the selection the user has built (and, under view scope, without
  // asking the server for the whole view).
  describe('explicit paths override (context menu)', () => {
    let dialog: MatDialog;
    let addPhotos: Mock;
    let writeText: Mock;
    let clipboardDescriptor: PropertyDescriptor | undefined;
    const photo = (path: string, extra: Record<string, unknown> = {}) => ({ path, filename: path.slice(1), ...extra });

    function selectThree(): void {
      mockStore.photos.set([photo('/a.jpg'), photo('/b.jpg'), photo('/c.jpg'), photo('/x.jpg')]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg', '/c.jpg']));
      mockStore.selectionCount.set(3);
    }

    function selectView(): void {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      mockStore.total.set(650);
    }

    beforeEach(() => {
      dialog = TestBed.inject(MatDialog);
      addPhotos = TestBed.inject(AlbumService).addPhotos as unknown as Mock;
      writeText = vi.fn(() => Promise.resolve());
      clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      selectThree();
    });

    afterEach(() => {
      if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
      else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    });

    const copy = (paths?: string[]) =>
      component.selectionActions.copyPaths(paths);
    const download = (paths?: string[]) =>
      component.selectionActions
        .downloadSelected('original', undefined, paths);

    it('addToAlbum adds exactly the given paths and leaves the selection alone', async () => {
      await component.selectionActions.addToAlbum(3, ['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect(mockStore.pathsInView).not.toHaveBeenCalled();
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('an empty paths list is a no-op, never a fall-back to the selection', async () => {
      await component.selectionActions.addToAlbum(3, []);
      await copy([]);

      expect(addPhotos).not.toHaveBeenCalled();
      expect(writeText).not.toHaveBeenCalled();
    });

    it('addToAlbum without paths still adds the selection and clears it', async () => {
      await component.selectionActions.addToAlbum(3);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/a.jpg', '/b.jpg', '/c.jpg']);
      expect(mockStore.clearSelection).toHaveBeenCalled();
    });

    it('createAlbumAndAdd forwards the paths to addToAlbum', async () => {
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of({ id: 9, name: 'N' }) });

      await component.selectionActions.createAlbumAndAdd(['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(9, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    describe('under a whole-view selection', () => {
      beforeEach(() => {
        selectView();
        mockStore.pathsInView.mockResolvedValue(['/q.jpg']);
      });

      it('addToAlbum, copyPaths and downloadSelected use the given paths without asking the server', async () => {
        await component.selectionActions.addToAlbum(3, ['/x.jpg']);
        await copy(['/x.jpg']);
        await download(['/x.jpg']);

        expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg']);
        expect(writeText).toHaveBeenCalledWith('x.jpg');
        expect(mockApi.downloadUrl).toHaveBeenCalledWith('/x.jpg', 'original', undefined);
        expect(mockStore.countInView).not.toHaveBeenCalled();
        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(dialog.open).not.toHaveBeenCalled();
      });
    });

    it('copyPaths writes the basenames of the given paths', async () => {
      await copy(['/d/one.jpg']);

      expect(writeText).toHaveBeenCalledWith('one.jpg');
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('downloadSelected downloads only the given paths', async () => {
      await download(['/x.jpg']);

      expect(mockApi.downloadUrl).toHaveBeenCalledTimes(1);
      expect(mockApi.downloadUrl).toHaveBeenCalledWith('/x.jpg', 'original', undefined);
    });

    describe('openExportDialog', () => {
      it('opens the dialog for the given paths even on an album route', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');

        component.selectionActions.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });

      it('exports the live selection, not the whole album, on an album route when no paths are given', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');

        component.selectionActions.openExportDialog();

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/a.jpg', '/b.jpg', '/c.jpg'] });
      });

      it('still exports the whole album on an album route when nothing is selected', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');
        mockStore.selectedPaths.set(new Set());
        mockStore.selectionCount.set(0);

        component.selectionActions.openExportDialog();

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
      });

      it('ignores view scope when paths are given', () => {
        selectView();

        component.selectionActions.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });
    });

    describe('openCullDialog', () => {
    beforeEach(() => { mockAuth['isEdition'] = vi.fn(() => true); });
      // The real store's loadPhotos() ends a whole-view selection, and its
      // selection methods move the signals. An inert mock hides both.
      beforeEach(() => {
        const setScope = (view: boolean, selected: Iterable<string>, excluded: Iterable<string>) => {
          mockStore.viewScopeSelected.set(view);
          mockStore.selectionScope.set(view ? 'view' : 'paths');
          mockStore.selectedPaths.set(new Set(selected));
          mockStore.excludedPaths.set(new Set(excluded));
        };
        mockStore.loadPhotos.mockImplementation(() => {
          if (mockStore.viewScopeSelected()) setScope(false, [], []);
          return Promise.resolve();
        });
        mockStore.selectWholeView.mockImplementation(() => setScope(true, [], []));
        mockStore.restoreSelection.mockImplementation((paths: Iterable<string>) => setScope(false, paths, []));
        mockStore.toggleSelection.mockImplementation((p: { path: string }) => {
          const target = mockStore.viewScopeSelected() ? mockStore.excludedPaths : mockStore.selectedPaths;
          const next = new Set(target());
          if (!next.delete(p.path)) next.add(p.path);
          target.set(next);
        });
      });

      it('sends the given paths with no filter even under view scope', async () => {
        selectView();
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.selectionActions.openCullDialog(['/x.jpg']);

        const data = (dialog.open as Mock).mock.calls[0][1].data;
        expect(data.paths).toEqual(['/x.jpg']);
        expect(data.filters).toBeNull();
        expect(data.exclude).toEqual([]);
        expect(data.count).toBe(1);
        expect(mockStore.reloadPhotos).toHaveBeenCalled();
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('keeps the whole-view selection across the reload, with the culled photo now excluded', async () => {
        selectView();
        mockStore.excludedPaths.set(new Set(['/e.jpg']));
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.selectionActions.openCullDialog(['/x.jpg']);

        expect(mockStore.viewScopeSelected()).toBe(true);
        expect(mockStore.selectionScope()).toBe('view');
        expect([...mockStore.excludedPaths()].sort()).toEqual(['/e.jpg', '/x.jpg']);
      });

      it('drops the target from a path selection, and only it', async () => {
        mockStore.selectedPaths.set(new Set(['/a.jpg', '/x.jpg']));
        mockStore.selectionCount.set(2);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.selectionActions.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()]).toEqual(['/a.jpg']);
        expect(mockStore.selectionScope()).toBe('paths');
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('leaves a path selection alone when the target was not selected', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.selectionActions.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('touches nothing when the dialog is dismissed', async () => {
        mockStore.selectedPaths.set(new Set(['/x.jpg']));
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.selectionActions.openCullDialog(['/x.jpg']);

        expect(mockStore.loadPhotos).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
      });
    });

    describe('deleteSelected', () => {
      const confirmed = { includeCompanions: false, includeSequenceSiblings: false };
      const deleted = (paths: string[]) => of({
        dry_run: false, deleted: paths, not_found: [], not_visible: [], refused_bracket_lead: [],
        sequence_siblings: [], skipped: [], removed_missing: [], trashed: paths.length, errors: {},
      });

      it('opens the single-photo dialog under view scope, where the no-arg form refuses', async () => {
        selectView();
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.selectionActions.deleteSelected(['/x.jpg']);

        const data = (dialog.open as Mock).mock.calls[0][1].data;
        expect(data.surface).toBe('photo_detail');
        expect(data.paths).toEqual(['/x.jpg']);
        expect(data.count).toBe(1);
      });

      it('removes only the deleted path and does not clear the selection', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(confirmed) });
        mockApi.post.mockReturnValueOnce(deleted(['/x.jpg']));

        await component.selectionActions.deleteSelected(['/x.jpg']);

        expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', expect.objectContaining({ paths: ['/x.jpg'] }));
        expect(mockStore.removePhotos).toHaveBeenCalledWith(['/x.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('returns without a dialog when the photo is no longer loaded', async () => {
        await component.selectionActions.deleteSelected(['/gone.jpg']);

        expect(dialog.open).not.toHaveBeenCalled();
      });

      it('flags a bracket base exposure as a lead, and nothing else', async () => {
        mockStore.photos.set([
          photo('/lead.jpg', { sequence_kind: 'bracket', sequence_ev_offset: 0 }),
          photo('/dark.jpg', { sequence_kind: 'bracket', sequence_ev_offset: -2 }),
          photo('/pano.jpg', { sequence_kind: 'panorama', sequence_ev_offset: 0 }),
        ]);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });
        const leadOf = async (path: string) => {
          (dialog.open as Mock).mockClear();
          await component.selectionActions.deleteSelected([path]);
          return (dialog.open as Mock).mock.calls[0][1].data;
        };

        expect((await leadOf('/lead.jpg')).hasBracketLead).toBe(true);
        expect((await leadOf('/lead.jpg')).hasSiblings).toBe(true);
        expect((await leadOf('/dark.jpg')).hasBracketLead).toBe(false);
        expect((await leadOf('/pano.jpg')).hasBracketLead).toBe(false);
        expect((await leadOf('/pano.jpg')).hasSiblings).toBe(true);
      });

      it('without paths still refuses under view scope', async () => {
        selectView();

        await component.selectionActions.deleteSelected();

        expect(dialog.open).not.toHaveBeenCalled();
      });
    });
  });

  describe('onPhotoMenuAction', () => {
    interface Menu {
      onPhotoMenuAction(e: { action: unknown; photo: unknown; bulk: boolean }): Promise<void>;
      runSelectionAction(a: unknown): Promise<void>;
    }
    const menu = () => component as unknown as Menu;
    const target = { path: '/x.jpg', filename: 'x.jpg' };
    const spy = (name: string) =>
      vi.spyOn((name in component.selectionActions ? component.selectionActions : component) as unknown as Record<string, (...a: unknown[]) => unknown>, name)
        .mockResolvedValue(undefined);

    beforeEach(() => {
      mockStore.photos.set([target]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg', '/c.jpg']));
      mockStore.selectionCount.set(3);
    });

    it('routes a bulk action through runSelectionAction, never the per-photo store calls', async () => {
      const run = vi.spyOn(menu() as unknown as { runSelectionAction(a: unknown): Promise<void> }, 'runSelectionAction')
        .mockResolvedValue();

      await menu().onPhotoMenuAction({ action: { kind: 'favorite' }, photo: target, bulk: true });

      expect(run).toHaveBeenCalledTimes(1);
      expect(run).toHaveBeenCalledWith({ kind: 'favorite' });
      expect(mockStore.toggleFavorite).not.toHaveBeenCalled();
    });

    describe('runSelectionAction covers every sheet kind', () => {
      const cases: [string, unknown, string, unknown[]][] = [
        ['favorite', { kind: 'favorite' }, 'batchFavorite', []],
        ['reject', { kind: 'reject' }, 'batchReject', []],
        ['rate', { kind: 'rate', rating: 4 }, 'batchRate', [4]],
        ['album', { kind: 'album', albumId: 5 }, 'addToAlbum', [5]],
        ['create-album', { kind: 'create-album' }, 'createAlbumAndAdd', []],
        ['invert', { kind: 'invert' }, 'invertSelection', []],
        ['compare', { kind: 'compare' }, 'compareSelection', []],
        ['export', { kind: 'export' }, 'openExportDialog', []],
        ['cull', { kind: 'cull' }, 'openCullDialog', []],
        ['delete', { kind: 'delete' }, 'deleteSelected', []],
        ['copy', { kind: 'copy' }, 'copyPaths', []],
        ['mark-panorama', { kind: 'mark-panorama', sequenceKind: 'bracket' }, 'markAsPanorama', ['bracket']],
        ['download', { kind: 'download', type: 'darktable', profile: 'P' }, 'downloadSelected', ['darktable', 'P']],
        ['tags', { kind: 'tags' }, 'openManualTagsDialog', []],
        ['capture-date', { kind: 'capture-date' }, 'openCaptureDateDialog', []],
        ['gps', { kind: 'gps' }, 'openBatchGpsDialog', []],
      ];
      for (const [name, action, method, args] of cases) {
        it(`${name} -> ${method}`, async () => {
          const target = spy(method);

          await menu().runSelectionAction(action);

          expect(target).toHaveBeenCalledTimes(1);
          expect(target).toHaveBeenCalledWith(...args);
        });
      }
    });

    describe('single photo', () => {
      const single = (action: unknown) =>
        menu().onPhotoMenuAction({ action, photo: target, bulk: false });

      afterEach(() => {
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
        expect(mockStore.batchReject).not.toHaveBeenCalled();
        expect(mockStore.batchRating).not.toHaveBeenCalled();
      });

      it('toggle-favorite toggles that one photo', async () => {
        await single({ kind: 'toggle-favorite' });
        expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/x.jpg');
      });

      it('toggle-reject toggles that one photo', async () => {
        await single({ kind: 'toggle-reject' });
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/x.jpg');
      });

      it('rate sets that one photo', async () => {
        await single({ kind: 'rate', rating: 3 });
        expect(mockStore.setRating).toHaveBeenCalledWith('/x.jpg', 3);
      });

      it('similar filters by that photo', async () => {
        await single({ kind: 'similar', mode: 'color' });
        expect(mockStore.updateFilters).toHaveBeenCalledWith(
          expect.objectContaining({ similar_to: '/x.jpg', similarity_mode: 'color' }));
      });

      const cases: [string, unknown, string, unknown[]][] = [
        ['open', { kind: 'open' }, 'downloadPhoto', [target]],
        ['critique', { kind: 'critique' }, 'openCritique', [target]],
        ['embed', { kind: 'embed' }, 'embedMetadata', [target]],
        ['assign-face', { kind: 'assign-face' }, 'openAddPerson', [target]],
        ['album', { kind: 'album', albumId: 5 }, 'addToAlbum', [5, ['/x.jpg']]],
        ['create-album', { kind: 'create-album' }, 'createAlbumAndAdd', [['/x.jpg']]],
        ['copy', { kind: 'copy' }, 'copyPaths', [['/x.jpg']]],
        ['export', { kind: 'export' }, 'openExportDialog', [['/x.jpg']]],
        ['cull', { kind: 'cull' }, 'openCullDialog', [['/x.jpg']]],
        ['delete', { kind: 'delete' }, 'deleteSelected', [['/x.jpg']]],
        ['download', { kind: 'download', type: 'raw' }, 'downloadSelected', ['raw', undefined, ['/x.jpg']]],
      ];
      for (const [name, action, method, args] of cases) {
        it(`${name} -> ${method} on that path only`, async () => {
          const called = spy(method);

          await single(action);

          expect(called).toHaveBeenCalledTimes(1);
          expect(called).toHaveBeenCalledWith(...args);
        });
      }

      it('the bulk-only kinds do nothing', async () => {
        const run = spy('runSelectionAction');
        for (const kind of ['invert', 'compare']) await single({ kind });
        await single({ kind: 'mark-panorama', sequenceKind: 'panorama' });
        await single({ kind: 'tags' });
        expect(run).not.toHaveBeenCalled();
        expect(mockStore.updateFilters).not.toHaveBeenCalled();
        expect(mockStore.toggleFavorite).not.toHaveBeenCalled();
      });

      it('leaves the multi-photo selection untouched', async () => {
        spy('copyPaths');
        await single({ kind: 'copy' });
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(mockStore.restoreSelection).not.toHaveBeenCalled();
      });
    });
  });

  describe('onGridFocusOut and the photo menu overlay', () => {
    const focusOut = (next: HTMLElement | null) =>
      (component as unknown as { onGridFocusOut(e: FocusEvent): void })
        .onGridFocusOut({ relatedTarget: next } as unknown as FocusEvent);

    it('keeps the cursor when focus moves into the cdk overlay container', () => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(1);
      const container = document.createElement('div');
      container.className = 'cdk-overlay-container';
      const item = document.createElement('button');
      container.appendChild(item);
      document.body.appendChild(container);

      focusOut(item);
      container.remove();

      expect(activeIndex()).toBe(1);
    });

    it('still drops the cursor when focus goes somewhere unrelated', () => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(1);
      const other = document.createElement('button');
      document.body.appendChild(other);

      focusOut(other);
      other.remove();

      expect(activeIndex()).toBe(-1);
    });
  });

  describe('photo context menu (rendered)', () => {
    const TOUCH = '(hover: none) and (pointer: coarse)';
    const photos = Array.from({ length: 12 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
      is_favorite: false, is_rejected: false, unassigned_faces: 0,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function render(mode: 'grid' | 'mosaic', virtual: boolean, touch = false): HTMLElement[] {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockStore.photos.set(photos);
      mockStore.config.set({ features: { show_rating_controls: true, show_similar_button: true } });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      const wide = mode === 'mosaic' || virtual;
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: media === TOUCH ? touch : wide,
        media, addEventListener() {}, removeEventListener() {},
      }));
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      if (wide) {
        instance.desktop.setup();
        instance.containerWidth.set(1200);
      }
      fixture.detectChanges();
      // The touch reading lands in afterNextRender, after the first pass.
      TestBed.tick();
      fixture.detectChanges();
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe(mode);
      expect(fixture.componentInstance.virtualOn()).toBe(virtual);
      return [...fixture.nativeElement.querySelectorAll('app-photo-card')] as HTMLElement[];
    }

    function rightClick(card: HTMLElement): MouseEvent {
      const ev = new MouseEvent('contextmenu', {
        button: 2, clientX: 20, clientY: 20, bubbles: true, cancelable: true,
      });
      card.dispatchEvent(ev);
      fixture!.detectChanges();
      return ev;
    }

    const panel = () => document.querySelector('.mat-mdc-menu-panel') as HTMLElement | null;
    const panelCount = () => document.querySelectorAll('.mat-mdc-menu-panel').length;

    for (const [name, mode, virtual] of [
      ['plain grid', 'grid', false],
      ['mosaic', 'mosaic', false],
      ['windowed rows', 'mosaic', true],
    ] as const) {
      describe(name, () => {
        it('opens the menu and suppresses the native one', () => {
          const cards = render(mode, virtual);

          const ev = rightClick(cards[cards.length - 2]);

          expect(ev.defaultPrevented).toBe(true);
          expect(panel()).not.toBeNull();
        });

        it('leaves the native menu on a touch-first device', () => {
          const cards = render(mode, virtual, true);

          const ev = rightClick(cards[cards.length - 2]);

          expect(ev.defaultPrevented).toBe(false);
          expect(panel()).toBeNull();
        });
      });
    }

    it('hides the floating tooltip when the menu opens', () => {
      const cards = render('grid', false);
      (fixture!.componentInstance as unknown as { tooltipPhoto: { set(v: unknown): void; (): unknown } })
        .tooltipPhoto.set(photos[0]);

      rightClick(cards[1]);

      expect((fixture!.componentInstance as unknown as { tooltipPhoto(): unknown }).tooltipPhoto()).toBeNull();
    });

    it('opens the single-photo menu on an unselected photo, leaving the selection alone', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p0.jpg', '/p1.jpg', '/p2.jpg']));
      mockStore.selectionCount.set(3);
      fixture!.detectChanges();

      rightClick(cards[5]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
      expect(panel()!.textContent).not.toContain(I18N.gallery.selection.mark_sequence);
      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('opens the bulk menu on a photo inside a multi-photo selection', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p0.jpg', '/p1.jpg', '/p2.jpg']));
      mockStore.selectionCount.set(3);
      fixture!.detectChanges();

      rightClick(cards[1]);

      expect(panel()!.textContent).toContain(I18N.gallery.selection.mark_sequence);
      expect(panel()!.textContent).not.toContain(I18N.shortcuts.open_detail);
      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
    });

    it('treats the sole selected photo as a single-photo menu', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p1.jpg']));
      mockStore.selectionCount.set(1);
      fixture!.detectChanges();

      rightClick(cards[1]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
    });

    it('treats an excluded photo under view scope as a single-photo menu', () => {
      const cards = render('grid', false);
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/p3.jpg']));
      mockStore.selectionCount.set(11);
      fixture!.detectChanges();

      rightClick(cards[3]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
    });

    it('opens from a nested control inside the card too', () => {
      const cards = render('grid', false);

      const ev = new MouseEvent('contextmenu', { button: 2, bubbles: true, cancelable: true });
      (cards[2].querySelector('button') ?? cards[2]).dispatchEvent(ev);
      fixture!.detectChanges();

      expect(ev.defaultPrevented).toBe(true);
      expect(panel()).not.toBeNull();
    });

    it('does not change the selection on a right mouse-down', () => {
      const cards = render('grid', false);

      cards[2].dispatchEvent(new MouseEvent('mousedown', { button: 2, bubbles: true }));
      cards[2].dispatchEvent(new MouseEvent('pointerdown', { button: 2, bubbles: true }));

      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
    });

    it('keeps exactly one panel when a second right-click lands while it is open', () => {
      const cards = render('grid', false);
      rightClick(cards[1]);

      rightClick(cards[1]);

      expect(panelCount()).toBe(1);
    });

    it('runs a picked single action against that photo', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      const item = [...document.querySelectorAll('.mat-mdc-menu-item')]
        .find(e => e.textContent?.includes(I18N.rating.add_favorite)) as HTMLElement;
      item.click();
      fixture!.detectChanges();

      expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/p4.jpg');
    });

    it('returns focus to the card when the menu is closed with Escape', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      panel()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true }));
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(true);
    });

    it('returns focus to the card after an item is picked', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      (document.querySelector('.mat-mdc-menu-item') as HTMLElement).click();
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(true);
    });

    it('has the card focused at the moment a picked action opens its dialog', () => {
      const cards = render('grid', false);
      let focusedCard = false;
      vi.spyOn(fixture!.componentInstance.selectionActions, 'openExportDialog')
        .mockImplementation(() => { focusedCard = cards[4].contains(document.activeElement); });
      rightClick(cards[4]);

      const item = [...document.querySelectorAll('.mat-mdc-menu-item')]
        .find(e => e.textContent?.includes(I18N.export.action)) as HTMLElement;
      item.click();
      fixture!.detectChanges();

      expect(focusedCard).toBe(true);
    });

    for (const [name, mode, virtual] of [
      ['plain grid', 'grid', false],
      ['mosaic', 'mosaic', false],
      ['windowed rows', 'mosaic', true],
    ] as const) {
      it(`keeps the cursor on the right-clicked card after Open and Back (${name})`, () => {
        const cards = render(mode, virtual);
        const events = TestBed.inject(Router).events as Subject<RouterEvent>;
        vi.spyOn(TestBed.inject(Router), 'navigate').mockImplementation(() => {
          events.next(new NavigationStart(1, '/photo'));
          return Promise.resolve(true);
        });
        const gallery = fixture!.componentInstance as unknown as { activeIndex(): number; scrollContent(): { scrollTo(o: ScrollToOptions): void } };
        // jsdom has no Element.scrollTo.
        vi.spyOn(gallery.scrollContent(), 'scrollTo').mockImplementation(() => {});
        const tile = cards[4].querySelector('[tabindex]') as HTMLElement;
        rightClick(cards[4]);
        const open = [...document.querySelectorAll('.mat-mdc-menu-item')]
          .find(e => e.textContent?.includes(I18N.shortcuts.open_detail)) as HTMLElement;
        open.click();
        fixture!.detectChanges();
        outletMock.detachEvents.next(fixture!.componentInstance);
        tile.blur();
        outletMock.attachEvents.next(fixture!.componentInstance);
        expect(gallery.activeIndex()).toBe(4);
      });
    }

    it('does not steal focus when the menu is dismissed from its backdrop', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      (document.querySelector('.cdk-overlay-backdrop') as HTMLElement).click();
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(false);
    });
  });

  describe('pinned list layout', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;
    const paths = ['/g0.jpg', '/g1.jpg', '/g2.jpg', '/g3.jpg', '/g4.jpg', '/g5.jpg', '/g6.jpg'];
    const photos = paths.map(path => ({ path, filename: path, image_width: 4000, image_height: 3000, tags_list: [], persons: [] }));

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function pin(): void {
      mockStore.photos.set(photos);
      mockStore.pinnedPaths.set(paths);
    }

    function render(mode: 'grid' | 'mosaic', virtual: boolean): HTMLElement {
      mockStore.config.set({ features: { show_rating_controls: true } });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
      }));
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      instance.desktop.setup();
      instance.containerWidth.set(1200);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    for (const [name, mode, virtual] of [
      ['virtual scroll off', 'grid', false],
      ['virtual scroll on', 'grid', true],
      ['mosaic', 'mosaic', false],
    ] as const) {
      it(`renders every card of the pinned list with no group heading (${name})`, () => {
        pin();
        const html = render(mode, virtual);
        expect(html.querySelectorAll('[role="heading"][aria-level]')).toHaveLength(0);
        expect(html.querySelectorAll('app-photo-card')).toHaveLength(7);
      });
    }

    it('offers no filter links on any rendered card, tooltip or menu in a pinned list, and restores them after the pin ends', () => {
      pin();
      render('grid', false);
      const f = fixture!;
      const cards = () => f.debugElement.queryAll(By.directive(PhotoCardComponent)).map(c => c.componentInstance as PhotoCardComponent);
      const tips = () => f.debugElement.queryAll(By.directive(PhotoTooltipComponent)).map(t => t.componentInstance as PhotoTooltipComponent);
      const menu = () => f.debugElement.query(By.directive(GalleryPhotoMenuComponent)).componentInstance as GalleryPhotoMenuComponent;
      expect(cards()).toHaveLength(7);
      expect(cards().map(c => c.filterLinks())).toEqual(Array(7).fill(false));
      expect(tips().map(t => t.personLinks()).every(v => v === false)).toBe(true);
      expect(menu().findSimilar()).toBe(false);
      mockStore.pinnedPaths.set(null);
      f.detectChanges();
      expect(cards().length).toBeGreaterThan(0);
      expect(cards().map(c => c.filterLinks()).every(v => v === true)).toBe(true);
      expect(tips().map(t => t.personLinks()).every(v => v === true)).toBe(true);
      expect(menu().findSimilar()).toBe(true);
    });

    it('honours the mosaic mode below md once the container has a width', () => {
      pin();
      mockStore.galleryMode.set('mosaic');
      mockStore.virtualScroll.set(false);
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: false, media, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
      }));
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      instance.desktop.setup();
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe('grid');
      instance.containerWidth.set(375);
      fixture.detectChanges();
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe('mosaic');
      expect(fixture.componentInstance.rowsModel().length).toBeGreaterThan(1);
    });

    it('reports the row count in aria-rowcount on the windowed branch', () => {
      pin();
      const html = render('grid', true);
      const rows = fixture!.componentInstance.rowsModel();
      expect(rows.length).toBe(3);
      expect(html.querySelector('#gallery-rows-host')?.getAttribute('aria-rowcount')).toBe('3');
    });

    describe('first frame width', () => {
      function renderMeasured(width: number): ComponentFixture<GalleryComponent> {
        const host = document.createElement('mat-sidenav-content');
        // The box the ResizeObserver reports: the client width (no scrollbar) less the horizontal padding.
        Object.defineProperty(host, 'clientWidth', { value: width + 32 });
        host.style.paddingLeft = '16px';
        host.style.paddingRight = '16px';
        host.getBoundingClientRect = () => ({ width: width + 17, height: 600, top: 0, left: 0, right: width, bottom: 600, x: 0, y: 0, toJSON() { return {}; } });
        document.body.appendChild(host);
        vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
        vi.stubGlobal('matchMedia', (media: string) => ({
          matches: true, media, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
        }));
        mockStore.config.set({ features: { show_rating_controls: true } });
        mockStore.galleryMode.set('grid');
        mockStore.virtualScroll.set(false);
        fixture = TestBed.createComponent(GalleryComponent);
        fixture.detectChanges();
        TestBed.tick();
        return fixture;
      }

      afterEach(() => document.querySelectorAll('mat-sidenav-content').forEach(el => el.remove()));

      it('lays the first rowsModel out for the measured width, with no ResizeObserver tick', () => {
        pin();
        const f = renderMeasured(800);
        const rows = f.componentInstance.rowsModel();
        expect(rows.length).toBeGreaterThan(0);
        for (const row of rows) {
          expect(row.widths.reduce((x, y) => x + y, 0)).toBeLessThanOrEqual(768);
        }
        expect((f.componentInstance as unknown as { containerWidth: () => number }).containerWidth()).toBe(800);
      });
    });

    it('fills the grid card as a square when details are hidden (fillTile set by the gallery)', () => {
      pin();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: true });
      render('grid', false);
      const card = fixture!.nativeElement.querySelector('app-photo-card') as HTMLElement;
      const tile = card.querySelector('[role="button"]') as HTMLElement;
      expect(tile.classList.contains('aspect-square')).toBe(true);
      expect(card.querySelector('img')!.classList.contains('object-cover')).toBe(true);
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    it('keeps the original ratio when the tile fit is natural (no fill, natural row heights)', () => {
      pin();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: true, tile_fit: 'natural' });
      render('grid', false);
      const card = fixture!.nativeElement.querySelector('app-photo-card') as HTMLElement;
      const tile = card.querySelector('[role="button"]') as HTMLElement;
      expect(tile.classList.contains('aspect-square')).toBe(false);
      expect(card.querySelector('img')!.classList.contains('object-cover')).toBe(false);
      const row = fixture!.componentInstance.rowsModel()[0];
      expect(row.height).not.toBe(row.widths[0]);
      expect(card.closest('.grid')!.classList.contains('items-start')).toBe(true);
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    it('sizes each windowed natural-fit card from the row model, not the row height', () => {
      pin();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: true, tile_fit: 'natural' });
      render('grid', true);
      const row = fixture!.componentInstance.rowsModel()[0];
      const cards = Array.from(fixture!.nativeElement.querySelectorAll('app-photo-card')) as HTMLElement[];
      expect(row.heights).toHaveLength(row.photos.length);
      expect(cards.slice(0, row.photos.length).map(c => c.style.height))
        .toEqual(row.heights!.map(h => `${h}px`));
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    it('keeps equal-height cards when details are shown, whatever the tile fit', () => {
      pin();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: false, tile_fit: 'natural' });
      render('grid', false);
      const card = fixture!.nativeElement.querySelector('app-photo-card') as HTMLElement;
      expect(card.closest('.grid')!.classList.contains('items-start')).toBe(false);
      expect(fixture!.componentInstance.rowsModel().every(r => r.heights === undefined)).toBe(true);
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    it('builds rows with the real hide_details setting', () => {
      pin();
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: false });
      render('grid', false);
      const photoRow = fixture!.componentInstance.rowsModel()[0];
      const cellW = photoRow.widths[0];
      expect(photoRow.height).toBeGreaterThan(Math.round(cellW * 3 / 4));
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    describe('keyboard', () => {
      const inst = () => fixture!.componentInstance as unknown as {
        activeIndex: { (): number; set(v: number): void };
        onGridKeydown(e: KeyboardEvent): void;
      };
      const pressOn = (key: string) => {
        const ev = new KeyboardEvent('keydown', { key });
        Object.defineProperty(ev, 'target', { value: null, configurable: true });
        inst().onGridKeydown(ev);
      };
      beforeEach(() => {
        pin();
        render('grid', true);
        Element.prototype.scrollIntoView = vi.fn();
      });

      it('ArrowDown steps to the same column of the next row on the windowed branch', () => {
        inst().activeIndex.set(1);
        pressOn('ArrowDown');
        expect(inst().activeIndex()).toBe(1 + fixture!.componentInstance.rowsModel()[0].photos.length);
      });

      it('ArrowDown on the last row stays put', () => {
        inst().activeIndex.set(6);
        pressOn('ArrowDown');
        expect(inst().activeIndex()).toBe(6);
      });
    });
  });

  describe('K / R keys', () => {
    function fire(key: string): KeyboardEvent {
      const ev = new KeyboardEvent('keydown', { key, cancelable: true });
      Object.defineProperty(ev, 'target', { value: null, configurable: true });
      (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
      return ev;
    }

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg', '/c.jpg']);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockStore.toggleRejected.mockClear();
      mockStore.setRating.mockClear();
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(0);
    });

    afterEach(() => mockStore.pinnedPaths.set(null));

    it.each(['r', 'R'])('%s does nothing on a pinned list: no default prevented, no advance, no write', key => {
      const ev = fire(key);
      expect(ev.defaultPrevented).toBe(false);
      expect(activeIndex()).toBe(0);
      expect(mockStore.toggleRejected).not.toHaveBeenCalled();
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it.each(['k', 'K'])('%s keeps the focused photo on a pinned list', async key => {
      mockStore.batchReview = vi.fn().mockResolvedValue({ snapshot: new Map(), targeted: 1, count: 1 });
      const ev = fire(key);
      expect(ev.defaultPrevented).toBe(true);
      expect(mockStore.batchReview).toHaveBeenCalledWith(['/a.jpg'], 'kept', false);
      await Promise.resolve();
    });

    it('X still rejects for real', () => {
      fire('x');
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
    });
  });

  describe('card menus across real router parking', () => {
    let harness: RouterTestingHarness;
    let gallery: GalleryComponent;
    let allowPhoto: boolean;
    const photos = Array.from({ length: 3 }, (_, i) => ({
      path: `/p${i}.jpg`, filename: `p${i}.jpg`, image_width: 4000, image_height: 3000,
    }));

    beforeEach(async () => {
      // Keep the rendered gallery and Material directives; replace only the
      // ordinary unit suite's route/outlet stubs with the real router boundary.
      TestBed.resetTestingModule();
      allowPhoto = true;
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.photos.set(photos);
      mockStore.total.set(photos.length);
      mockStore.config.set({ features: { show_rating_controls: true } });
      TestBed.configureTestingModule({
        imports: [GalleryComponent, MenuPhotoRoute],
        providers: [
          provideRouter([
            { path: '', component: GalleryComponent },
            { path: 'photo', component: MenuPhotoRoute, canActivate: [() => allowPhoto] },
          ]),
          provideLocationMocks(),
          provideNativeDateAdapter(),
          { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
          { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
          { provide: GalleryStore, useValue: mockStore },
          { provide: ApiService, useValue: mockApi },
          { provide: AuthService, useValue: mockAuth },
          { provide: I18nService, useValue: mockI18n },
          { provide: AlbumService, useValue: { list: () => of({ albums: [] }) } },
          { provide: ScanService, useValue: { canLaunch: signal(false) } },
          { provide: LiveAnnouncer, useValue: { announce: () => Promise.resolve() } },
        ],
      });
      harness = await RouterTestingHarness.create();
      TestBed.inject(Router).initialNavigation();
      gallery = await harness.navigateByUrl('/', GalleryComponent);
      const content = harness.routeDebugElement!.query(By.directive(MatSidenavContent)).componentInstance as MatSidenavContent;
      vi.spyOn(content, 'scrollTo').mockImplementation(() => {});
      for (const host of harness.routeNativeElement!.querySelectorAll<HTMLElement>('[data-pidx]')) {
        host.scrollIntoView = () => {};
      }
    });

    const overlay = () => TestBed.inject(OverlayContainer).getContainerElement();
    it.each([false, true])('creates a fresh library tag visit and restores query on Back (already synced: %s)', async synced => {
      mockStore.filters.update((f: GalleryFilters) => ({ ...f, album_id: '8', date_from: '2026-10-01' }));
      if (synced) await TestBed.inject(Router).navigate([], { queryParams: buildSyncParams(mockStore.filters(), undefined), replaceUrl: true });
      const before = mockStore.loadConfig.mock.calls.length;
      await (gallery as unknown as { navigateTag(choice: { tag: string; scope: 'library' }): Promise<void> }).navigateTag({ tag: 'coast,ridge OR 夜景', scope: 'library' });
      await harness.fixture.whenStable(); harness.detectChanges();
      expect(harness.routeDebugElement!.componentInstance).not.toBe(gallery);
      expect(mockStore.loadConfig.mock.calls.length).toBe(before + 1);
      const url = new URL(TestBed.inject(Router).url, 'http://fixture');
      expect(url.searchParams.get('tag_groups')).toBe('{"all":["coast,ridge OR 夜景"]}');
      expect(url.searchParams.has('album_id')).toBe(false);
      expect(url.searchParams.has('date_from')).toBe(false);
      const fresh = harness.routeDebugElement!.componentInstance;
      const backDone = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
      TestBed.inject(Location).back(); await backDone; await harness.fixture.whenStable(); harness.detectChanges();
      expect(harness.routeDebugElement!.componentInstance).not.toBe(fresh);
      const restored = new URL(TestBed.inject(Router).url, 'http://fixture');
      expect(restored.searchParams.get('album_id')).toBe('8');
      expect(restored.searchParams.get('date_from')).toBe('2026-10-01');
      expect(restored.searchParams.has('tag_groups')).toBe(true);
      expect(mockStore.loadConfig.mock.calls.length).toBe(before + 2);
    });

    it('closes child-owned tooltip menus when the gallery parks', async () => {
      mockStore.filters.update((f: GalleryFilters) => ({ ...f, tooltip_mode: 'click' }));
      harness.detectChanges();
      const tooltips = harness.routeDebugElement!.queryAll(By.directive(PhotoTooltipComponent));
      const closes = tooltips.map(el => vi.spyOn(el.componentInstance as PhotoTooltipComponent, 'closeOverlays'));
      expect(closes.length).toBeGreaterThan(0);
      await harness.navigateByUrl('/photo', MenuPhotoRoute);
      expect(closes.every(close => close.mock.calls.length > 0)).toBe(true);
    });
    async function expectMenuRemoved(): Promise<void> {
      const container = overlay();
      if (container.querySelector('[role="menu"]')) {
        // Material completes overlay teardown asynchronously even with
        // animations disabled. Observe the real effect instead of sleeping.
        await new Promise<void>(resolve => {
          const observer = new MutationObserver(() => {
            if (!container.querySelector('[role="menu"]')) {
              observer.disconnect();
              resolve();
            }
          });
          observer.observe(container, { childList: true, subtree: true });
        });
      }
      expect(container.querySelector('[role="menu"]')).toBeNull();
    }
    const contextTrigger = (index: number) => harness.routeDebugElement!
      .queryAll(By.directive(MatContextMenuTrigger))[index].injector.get(MatContextMenuTrigger);
    async function rightClick(index: number): Promise<MatContextMenuTrigger> {
      const card = harness.routeNativeElement!.querySelector(`app-photo-card[data-pidx="${index}"]`)!;
      card.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2, clientX: 40, clientY: 50 }));
      harness.detectChanges();
      await harness.fixture.whenStable();
      const trigger = contextTrigger(index);
      expect(trigger.menuOpen).toBe(true);
      expect(overlay().querySelector('[role="menu"]')).not.toBeNull();
      return trigger;
    }
    async function back(): Promise<void> {
      const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
      TestBed.inject(Location).back();
      await done;
      harness.detectChanges();
      await harness.fixture.whenStable();
      expect(harness.routeDebugElement!.componentInstance).toBe(gallery);
    }

    it('removes the right-click overlay on photo navigation and reopens once after arrow navigation and Back', async () => {
      const dispatcher = TestBed.inject(ScrollDispatcher);
      const scrolled = dispatcher.scrolled.bind(dispatcher);
      let scrollSubscriptions = 0;
      vi.spyOn(dispatcher, 'scrolled').mockImplementation(ms => defer(() => {
        scrollSubscriptions++;
        return scrolled(ms).pipe(finalize(() => scrollSubscriptions--));
      }));
      const trigger = await rightClick(1);
      expect(scrollSubscriptions).toBeGreaterThan(0);
      const closed = vi.fn();
      trigger.menuClosed.subscribe(closed);
      await harness.navigateByUrl('/photo?path=%2Fp1.jpg', MenuPhotoRoute);
      await harness.fixture.whenStable();
      expect(mockStore.parkListingReads).toHaveBeenCalledOnce();
      expect(trigger.menuOpen).toBe(false);
      await expectMenuRemoved();
      expect(closed).toHaveBeenCalledOnce();
      expect(scrollSubscriptions).toBe(0);
      // Photo arrows replace the current entry; Back must retain that viewed
      // photo as the gallery cursor, without resurrecting the old menu.
      await TestBed.inject(Router).navigateByUrl('/photo?path=%2Fp2.jpg', { replaceUrl: true });
      await back();
      expect(document.activeElement?.closest('[data-pidx]')?.getAttribute('data-pidx')).toBe('2');
      await expectMenuRemoved();
      await rightClick(1);
      expect(scrollSubscriptions).toBeGreaterThan(0);
      expect(overlay().querySelectorAll('[role="menu"]')).toHaveLength(1);
      await harness.navigateByUrl('/photo?path=%2Fp1.jpg');
      await harness.fixture.whenStable();
      expect(closed).toHaveBeenCalledTimes(2);
      await expectMenuRemoved();
      expect(scrollSubscriptions).toBe(0);
    });

    it('keeps a context menu usable when photo navigation is cancelled, then closes on a successful retry', async () => {
      const trigger = await rightClick(0);
      allowPhoto = false;
      expect(await TestBed.inject(Router).navigateByUrl('/photo?path=%2Fp0.jpg')).toBe(false);
      expect(mockStore.parkListingReads).not.toHaveBeenCalled();
      expect(trigger.menuOpen).toBe(true);
      expect(overlay().querySelector('[role="menu"]')).not.toBeNull();
      allowPhoto = true;
      await harness.navigateByUrl('/photo?path=%2Fp0.jpg');
      await harness.fixture.whenStable();
      expect(trigger.menuOpen).toBe(false);
      await expectMenuRemoved();
      await back();
      await rightClick(0);
    });

    it('still closes an ordinary gallery menu across the real outlet detach', async () => {
      mockStore.selectionCount.set(1);
      harness.detectChanges();
      const trigger = harness.routeDebugElement!.query(By.directive(MatMenuTrigger)).injector.get(MatMenuTrigger);
      trigger.openMenu();
      harness.detectChanges();
      await harness.fixture.whenStable();
      expect(trigger.menuOpen).toBe(true);
      expect(overlay().querySelector('[role="menu"]')).not.toBeNull();
      await harness.navigateByUrl('/photo?path=%2Fp0.jpg');
      await harness.fixture.whenStable();
      expect(trigger.menuOpen).toBe(false);
      await expectMenuRemoved();
    });
  });

  describe('side drawer margins across a park (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    it('recomputes the content margin on return after a resize measured the detached drawer as 0', async () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.photos.set([{ path: '/p0.jpg', filename: 'p0.jpg', image_width: 4000, image_height: 3000 }]);
      mockStore.total.set(1);
      mockStore.filterDrawerOpen.set(true);
      vi.stubGlobal('matchMedia', (media: string) => ({ matches: true, media, addEventListener() {}, removeEventListener() {} }));
      fixture = TestBed.createComponent(GalleryComponent);
      (fixture.componentInstance as unknown as { desktop: { setup(): void } }).desktop.setup();
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      const sidenav = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as unknown as {
        mode: string; opened: boolean; _getWidth: () => number; _elementRef: { nativeElement: HTMLElement };
      };
      const container = fixture.debugElement.query(By.directive(MatSidenavContainer)).componentInstance as unknown as {
        updateContentMargins(): void; _contentMargins: { left: number | null; right: number | null };
      };
      const contentEl = fixture.debugElement.query(By.directive(MatSidenavContent)).nativeElement as HTMLElement;
      expect(sidenav.mode).toBe('side');
      expect(sidenav.opened).toBe(true);
      // jsdom has no layout: emulate a 320px drawer that measures 0 once out of the document.
      sidenav._getWidth = () => (sidenav._elementRef.nativeElement.isConnected ? 320 : 0);
      container.updateContentMargins();
      fixture.detectChanges();
      expect(container._contentMargins.right).toBe(320);
      expect(contentEl.style.marginRight).toBe('320px');
      // Park: the outlet takes the DOM out, then emits detach.
      const host = fixture.nativeElement as HTMLElement;
      const parent = host.parentNode as Node;
      host.remove();
      outletMock.detachEvents.next(fixture.componentInstance);
      window.dispatchEvent(new Event('resize'));
      await new Promise(resolve => setTimeout(resolve, 60));
      expect(container._contentMargins.right).toBeNull();
      // Return: the outlet re-inserts the DOM, then emits attach.
      parent.appendChild(host);
      outletMock.attachEvents.next(fixture.componentInstance);
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(container._contentMargins.right).toBe(320);
      expect(contentEl.style.marginRight).toBe('320px');
    });
  });

  describe('review-progress banner (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent>;

    function render(wide = true): HTMLElement {
      mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) => (vars ? `${key} ${JSON.stringify(vars)}` : key));
      fixture = TestBed.createComponent(GalleryComponent);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(wide), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: signal(wide), configurable: true });
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    function buttonLabelled(host: HTMLElement, key: string): HTMLButtonElement | undefined {
      return Array.from(host.querySelectorAll('button')).find(b => b.textContent?.trim() === key);
    }

    afterEach(() => {
      fixture.destroy();
      sessionStorage.removeItem(NOTICE_DISMISSALS_KEY);
    });

    it('closes for this tab without hiding it for good, and reopens for another scope', () => {
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      const host = render();
      host.querySelector<HTMLButtonElement>(`[data-review-progress] button[aria-label="${I18N.ui.buttons.dismiss}"]`)!.click();
      fixture.detectChanges();
      expect(host.querySelector('[data-review-progress]')).toBeNull();
      expect(mockStore.setReviewProgressVisible).not.toHaveBeenCalled();

      // New counts in the same scope are still the same notice.
      mockStore.reviewProgress.set({ total: 10, undecided: 5, kept: 4, rejected: 1 });
      fixture.detectChanges();
      expect(host.querySelector('[data-review-progress]')).toBeNull();

      mockStore.filters.set({ ...DEFAULT_FILTERS, tag: 'beach' });
      fixture.detectChanges();
      expect(host.querySelector('[data-review-progress]')).not.toBeNull();
    });

    it('lets the Review popover show the banner again after its close button hid it for this tab', async () => {
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      mockStore.setReviewProgressVisible.mockImplementation((visible: boolean) => mockStore.reviewProgressVisible.set(visible));
      const host = render();
      host.querySelector<HTMLButtonElement>(`[data-review-progress] button[aria-label="${I18N.ui.buttons.dismiss}"]`)!.click();
      fixture.detectChanges();
      expect(host.querySelector('[data-review-progress]')).toBeNull();
      host.querySelector<HTMLButtonElement>('[data-collection-review] button')!.click();
      fixture.detectChanges(); await fixture.whenStable();
      const overlay = TestBed.inject(OverlayContainer).getContainerElement();
      expect(overlay.querySelector('label[data-review-progress-toggle], input[data-review-progress-toggle]')).toBeNull();
      const toggle = overlay.querySelector<HTMLInputElement>('mat-checkbox[data-review-progress-toggle] input')!;
      expect(toggle.checked).toBe(false);
      toggle.click();
      fixture.detectChanges();
      expect(mockStore.setReviewProgressVisible).toHaveBeenLastCalledWith(true);
      expect(host.querySelector('[data-review-progress]')).not.toBeNull();
      expect(toggle.checked).toBe(true);
      toggle.click();
      fixture.detectChanges();
      expect(mockStore.setReviewProgressVisible).toHaveBeenLastCalledWith(false);
      expect(host.querySelector('[data-review-progress]')).toBeNull();
    });

    it('renders nothing while there is no progress snapshot', () => {
      const host = render();
      expect(host.querySelector('section progress')).toBeNull();
    });

    it('shows no review notice when the scope holds no photos', () => {
      mockStore.reviewProgress.set({ total: 0, undecided: 0, kept: 0, rejected: 0 });
      expect(render().querySelector('[data-review-progress]')).toBeNull();
    });

    it('renders the decision counts and completion for the scope', () => {
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      mockStore.reviewPercent.set(40);
      const status = render().querySelector('[data-review-progress] [role="status"]') as HTMLElement;
      expect(status.textContent).toContain(`${I18N.gallery.review_progress.counts} ${JSON.stringify({ undecided: 6, kept: 3, rejected: 1 })}`);
      expect(status.textContent).toContain(`${I18N.gallery.review_progress.complete} ${JSON.stringify({ percent: 40, total: 10 })}`);
    });

    it('Start calls startReviewQueue', () => {
      mockStore.startReviewQueue = vi.fn();
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      const start = buttonLabelled(render(), I18N.gallery.review_progress.start);
      expect(start).toBeDefined();
      start!.click();
      expect(mockStore.startReviewQueue).toHaveBeenCalledTimes(1);
    });

    it('offers no Start when nothing is undecided or the undecided tab is already active', () => {
      mockStore.reviewProgress.set({ total: 10, undecided: 0, kept: 9, rejected: 1 });
      expect(buttonLabelled(render(), I18N.gallery.review_progress.start)).toBeUndefined();
      fixture.destroy();
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, review_status: 'undecided' });
      expect(buttonLabelled(render(), I18N.gallery.review_progress.start)).toBeUndefined();
    });

    it('Continue calls continueReview on the store', () => {
      mockStore.reviewBookmark.set({ path: '/p1.jpg' });
      const resume = buttonLabelled(render(), I18N.gallery.review_progress.resume);
      expect(resume).toBeDefined();
      resume!.click();
      expect(mockStore.continueReview).toHaveBeenCalledTimes(1);
    });
  });

  describe('notice stack auto-collapse (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent>;
    /** The lg breakpoint of the last render, kept so a test can resize across it. */
    let lgWide: WritableSignal<boolean>;

    /** `wide` is the md signal; `lg` defaults to it, and false puts the viewport below lg where the stack is one bar. */
    function render(wide = true, lg = wide): HTMLElement {
      mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) => (vars ? `${key} ${JSON.stringify(vars)}` : key));
      fixture = TestBed.createComponent(GalleryComponent);
      lgWide = signal(lg);
      Object.defineProperty(fixture.componentInstance, 'isDesktop', { value: signal(wide), configurable: true });
      Object.defineProperty(fixture.componentInstance['lgDesktop'], 'isDesktop', { value: lgWide, configurable: true });
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    const stack = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-gallery-notices]');
    const pill = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-gallery-notices-pill]');
    const card = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-review-progress]');

    let matchesSpy: { mockRestore(): void } | null = null;

    /** jsdom has no input modality, so :focus-visible never matches: treat the
     *  focused element as keyboard-focused, which is what these specs simulate. */
    function keyboardModality(): void {
      const matches = Element.prototype.matches;
      matchesSpy = vi.spyOn(Element.prototype, 'matches').mockImplementation(function (this: Element, selector: string) {
        return selector === ':focus-visible' ? this === document.activeElement : matches.call(this, selector);
      });
    }

    function collapseAfterFullWindow(): void {
      vi.advanceTimersByTime(6000);
      fixture.detectChanges();
    }

    beforeEach(() => {
      vi.useFakeTimers();
      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
    });

    afterEach(() => {
      vi.useRealTimers();
      matchesSpy?.mockRestore();
      matchesSpy = null;
      fixture.destroy();
      sessionStorage.removeItem(NOTICE_DISMISSALS_KEY);
    });

    it('folds into a count pill after the window, and the pill expands again on click', () => {
      const host = render();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();

      collapseAfterFullWindow();
      expect(card(host)).toBeNull();
      expect(pill(host)).not.toBeNull();

      pill(host)!.click();
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();
    });

    it('renders the fold from the timer itself, without waiting for a change detection pass', async () => {
      const host = render();
      vi.advanceTimersByTime(6000);
      expect(pill(host)).not.toBeNull();
      // Nothing is left pending, so the fixture settles while the stack stays folded.
      await fixture.whenStable();
      expect(pill(host)).not.toBeNull();
    });

    it('keeps the scroll-to-top button outside the collapse', () => {
      const host = render();
      (fixture.componentInstance as unknown as { showScrollTop: WritableSignal<boolean> }).showScrollTop.set(true);
      fixture.detectChanges();
      collapseAfterFullWindow();
      expect(pill(host)).not.toBeNull();
      expect(stack(host)!.querySelector('button[aria-label="gallery.scroll_to_top"]')).not.toBeNull();
    });

    it('leaves the stack alone while the pointer rests on it', () => {
      const host = render();
      stack(host)!.dispatchEvent(new Event('pointerenter', { bubbles: false }));
      fixture.detectChanges();
      vi.advanceTimersByTime(60000);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();

      stack(host)!.dispatchEvent(new Event('pointerleave', { bubbles: false }));
      fixture.detectChanges();
      vi.advanceTimersByTime(6000);
      fixture.detectChanges();
      expect(pill(host)).not.toBeNull();
    });

    it('re-expands with a fresh window when another notice joins', () => {
      const host = render();
      vi.advanceTimersByTime(4000);
      // A second notice joins before the window closes.
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();

      // The fresh window covers the full span from the new card's arrival.
      vi.advanceTimersByTime(5900);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      vi.advanceTimersByTime(100);
      fixture.detectChanges();
      expect(pill(host)).not.toBeNull();
    });

    it('counts the folded cards in the pill label', () => {
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      const host = render();
      collapseAfterFullWindow();
      expect(pill(host)!.textContent).toContain('gallery.notices.collapsed_plural');
      expect(pill(host)!.textContent).toContain('"count":2');
    });

    it('starts expanded again once every notice is gone', () => {
      const host = render();
      collapseAfterFullWindow();
      expect(pill(host)).not.toBeNull();

      mockStore.reviewProgress.set(null);
      fixture.detectChanges();
      expect(stack(host)).toBeNull();

      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();
    });

    it('folds again after a stack that vanished under the pointer comes back', () => {
      const host = render();
      stack(host)!.dispatchEvent(new Event('pointerenter', { bubbles: false }));
      // The last card leaves while the pointer rests on it: no pointerleave ever fires.
      mockStore.reviewProgress.set(null);
      fixture.detectChanges();
      expect(stack(host)).toBeNull();

      mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
      fixture.detectChanges();
      collapseAfterFullWindow();
      expect(pill(host)).not.toBeNull();
    });

    describe('below lg: one bar', () => {
      const bar = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-notice-bar]');
      const dismissAll = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-notice-dismiss-all]');
      const collapse = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-notices-collapse]');
      const twoNotices = () => mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });

      it('starts collapsed as ONE bar holding the count and a sibling Dismiss all, never auto-folding', () => {
        twoNotices();
        const host = render(true, false);
        expect(bar(host)).not.toBeNull();
        expect(card(host)).toBeNull();
        expect(pill(host)!.parentElement).toBe(bar(host));
        expect(dismissAll(host)!.parentElement).toBe(bar(host));
        expect(pill(host)!.contains(dismissAll(host))).toBe(false);
        expect(pill(host)!.textContent).toContain('"count":2');
        pill(host)!.click(); fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        vi.advanceTimersByTime(60000);
        fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        expect(pill(host)).toBeNull();
      });

      it('sizes the bar to its text on the right instead of spanning the screen', () => {
        const host = render(true, false);
        const classes = bar(host)!.classList;
        expect(classes).not.toContain('w-full');
        expect(classes).toContain('w-fit');
        expect(classes).toContain('max-w-full');
        expect(classes).toContain('self-end');
        expect(pill(host)!.classList).not.toContain('flex-1');
      });

      it('the expanded bar carries a collapse button next to Dismiss all, and a tap folds it', () => {
        twoNotices();
        const host = render(true, false);
        pill(host)!.click(); fixture.detectChanges();
        expect(collapse(host)!.textContent).toContain(I18N.gallery.notices.collapse);
        expect(collapse(host)!.querySelector('mat-icon')!.textContent).toBe('expand_more');
        expect(dismissAll(host)!.parentElement).toBe(collapse(host)!.parentElement);
        collapse(host)!.click(); fixture.detectChanges();
        expect(card(host)).toBeNull();
        expect(pill(host)).not.toBeNull();
      });

      it('stays as the user left it when the set of notices changes, and resets only when it empties', () => {
        twoNotices();
        const host = render(true, false);
        pill(host)!.click(); fixture.detectChanges();
        mockStore.reviewBookmark.set(null);
        fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        twoNotices();
        fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        collapse(host)!.click(); fixture.detectChanges();
        mockStore.reviewBookmark.set(null);
        fixture.detectChanges();
        expect(pill(host)).not.toBeNull();
        mockStore.reviewProgress.set(null);
        fixture.detectChanges();
        expect(stack(host)).toBeNull();
        mockStore.reviewProgress.set({ total: 10, undecided: 6, kept: 3, rejected: 1 });
        fixture.detectChanges();
        expect(card(host)).toBeNull();
        expect(pill(host)).not.toBeNull();
      });

      it('keeps the bar with its collapse button for a single expanded notice, so it can always fold back', () => {
        const host = render(true, false);
        expect(pill(host)!.parentElement).toBe(bar(host));
        pill(host)!.click(); fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        expect(collapse(host)!.parentElement).toBe(bar(host));
        expect(dismissAll(host)).toBeNull();
        collapse(host)!.click(); fixture.detectChanges();
        expect(card(host)).toBeNull();
        expect(pill(host)!.parentElement).toBe(bar(host));
      });

      it('keeps the collapse button when one of two expanded notices is dismissed', () => {
        twoNotices();
        const host = render(true, false);
        pill(host)!.click(); fixture.detectChanges();
        card(host)!.querySelector<HTMLElement>('[data-notice-close]')!.click();
        fixture.detectChanges();
        expect(stack(host)).not.toBeNull();
        expect(collapse(host)!.parentElement).toBe(bar(host));
        expect(dismissAll(host)).toBeNull();
      });

      it('Dismiss all in the bar clears every notice and parks focus on the grid scroller', () => {
        twoNotices();
        const host = render(true, false);
        const dismiss = dismissAll(host) as HTMLButtonElement;
        dismiss.focus(); dismiss.click();
        TestBed.tick();
        expect(stack(host)).toBeNull();
        expect(JSON.parse(sessionStorage.getItem(NOTICE_DISMISSALS_KEY)!)).toEqual(expect.objectContaining({
          review_progress: expect.any(Array), review_bookmark: expect.any(Array),
        }));
        expect(document.activeElement).toBe(fixture.componentInstance['scrollContent']()!.getElementRef().nativeElement);
      });

      it('hands focus from the collapse button to the pill that replaces it', () => {
        const host = render(true, false);
        pill(host)!.click(); fixture.detectChanges();
        const button = collapse(host)!;
        button.focus(); button.click();
        TestBed.tick();
        expect(document.activeElement).toBe(pill(host));
      });

      it('folds into the bar when the window narrows below lg, and never on a timer there', () => {
        const host = render(true, true);
        expect(card(host)).not.toBeNull();
        lgWide.set(false);
        fixture.detectChanges();
        expect(card(host)).toBeNull();
        expect(pill(host)!.parentElement).toBe(bar(host));
        pill(host)!.click(); fixture.detectChanges();
        vi.advanceTimersByTime(60000);
        fixture.detectChanges();
        expect(card(host)).not.toBeNull();
      });

      it('arms the fold timer when the window widens to lg with the bar expanded, and keeps a folded bar folded', () => {
        const host = render(true, false);
        lgWide.set(true);
        fixture.detectChanges();
        expect(bar(host)).toBeNull();
        expect(pill(host)).not.toBeNull();
        expect(card(host)).toBeNull();
        lgWide.set(false);
        fixture.detectChanges();
        pill(host)!.click(); fixture.detectChanges();
        lgWide.set(true);
        fixture.detectChanges();
        expect(card(host)).not.toBeNull();
        collapseAfterFullWindow();
        expect(card(host)).toBeNull();
        expect(pill(host)).not.toBeNull();
      });

      it('lg and wider keep the floating cards, the timer fold and no bar', () => {
        const host = render(true, true);
        expect(bar(host)).toBeNull();
        expect(card(host)).not.toBeNull();
        collapseAfterFullWindow();
        expect(pill(host)).not.toBeNull();
        expect(collapse(host)).toBeNull();
      });
    });

    it('below lg the bar waits out the mobile drawer and comes back as the user left it, never folding on a timer', () => {
      const host = render(false);
      pill(host)!.click(); fixture.detectChanges();
      vi.advanceTimersByTime(3000);
      mockStore.filterDrawerOpen.set(true);
      fixture.detectChanges();
      expect(stack(host)).toBeNull();
      outletMock.detachEvents.next(fixture.componentInstance);
      outletMock.attachEvents.next(fixture.componentInstance);
      vi.advanceTimersByTime(60000);
      mockStore.filterDrawerOpen.set(false);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      vi.advanceTimersByTime(60000);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();
    });

    it('re-expands for a card that joined while the drawer covered the folded stack', () => {
      const host = render();
      collapseAfterFullWindow();
      expect(pill(host)).not.toBeNull();
      mockStore.filterDrawerOpen.set(true);
      fixture.detectChanges();
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      fixture.detectChanges();

      mockStore.filterDrawerOpen.set(false);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();
      expect(pill(host)).toBeNull();
    });

    it.each([false, true])('dismisses all current notices without changing filters or the bookmark (collapsed=%s)', collapsed => {
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      const host = render();
      if (collapsed) collapseAfterFullWindow();
      const filters = mockStore.filters(); const bookmark = mockStore.reviewBookmark();
      const dismiss = host.querySelector<HTMLButtonElement>('[data-notice-dismiss-all]')!;
      expect(dismiss).not.toBeNull(); dismiss.focus(); dismiss.click();
      TestBed.tick();
      expect(stack(host)).toBeNull();
      expect(mockStore.filters()).toEqual(filters); expect(mockStore.reviewBookmark()).toEqual(bookmark);
      expect(mockStore.showAllHidden).not.toHaveBeenCalled();
      expect(JSON.parse(sessionStorage.getItem(NOTICE_DISMISSALS_KEY)!)).toEqual(expect.objectContaining({
        review_progress: expect.any(Array), review_bookmark: expect.any(Array),
      }));
      expect(document.activeElement).toBe(fixture.componentInstance['scrollContent']()!.getElementRef().nativeElement);
      // The dismissal applies to these notice signatures, not future scopes.
      mockStore.reviewBookmark.set({ path: '/p2.jpg', filters: { tag: 'new' } });
      fixture.detectChanges();
      expect(stack(host)?.textContent).toContain('gallery.review_progress.browser');
    });

    it('grants a fresh window when a card is dismissed', () => {
      mockStore.reviewBookmark.set({ path: '/p1.jpg', filters: { tag: 'a' } });
      const host = render();
      vi.advanceTimersByTime(4000);
      card(host)!.querySelector<HTMLElement>('[data-notice-close]')!.click();
      fixture.detectChanges();
      expect(card(host)).toBeNull();
      vi.advanceTimersByTime(5900);
      fixture.detectChanges();
      expect(pill(host)).toBeNull();
      vi.advanceTimersByTime(100);
      fixture.detectChanges();
      expect(pill(host)).not.toBeNull();
    });

    it('stays open while keyboard focus is on a card, and re-arms when focus leaves', () => {
      keyboardModality();
      const host = render();
      const close = card(host)!.querySelector<HTMLElement>('[data-notice-close]')!;
      close.focus();
      vi.advanceTimersByTime(60000);
      fixture.detectChanges();
      expect(card(host)).not.toBeNull();

      close.blur();
      fixture.detectChanges();
      collapseAfterFullWindow();
      expect(pill(host)).not.toBeNull();
    });

    it('hands keyboard focus from the pill to the first card, named by its visible count', () => {
      keyboardModality();
      const host = render();
      collapseAfterFullWindow();
      const button = pill(host)!;
      expect(button.hasAttribute('aria-expanded')).toBe(false);
      expect(button.hasAttribute('aria-label')).toBe(false);
      button.focus();
      button.click();
      TestBed.tick();
      expect(document.activeElement).toBe(card(host)!.querySelector('[data-notice-close]'));
    });
  });

  describe('leaving panel mode (rendered)', () => {
    it('releases the held photo when the mode switches away from panel', () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const comp = fixture.componentInstance as unknown as { activeIndex: WritableSignal<number>; releasePanel(): void };
      comp.activeIndex.set(0);
      const release = vi.spyOn(comp, 'releasePanel').mockImplementation(() => {});
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      fixture.detectChanges();
      expect(release).toHaveBeenCalledOnce();
      fixture.destroy();
    });

    it('does not release on Hover -> Click: activeIndex is the keyboard cursor in every mode', () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const comp = fixture.componentInstance as unknown as { activeIndex: WritableSignal<number>; releasePanel(): void };
      comp.activeIndex.set(0);
      const release = vi.spyOn(comp, 'releasePanel').mockImplementation(() => {});
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      fixture.detectChanges();
      expect(release).not.toHaveBeenCalled();
      fixture.destroy();
    });

    it('releases on Panel -> Click with a live cursor', () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const comp = fixture.componentInstance as unknown as { activeIndex: WritableSignal<number>; releasePanel(): void };
      comp.activeIndex.set(0);
      const release = vi.spyOn(comp, 'releasePanel').mockImplementation(() => {});
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      fixture.detectChanges();
      expect(release).toHaveBeenCalledOnce();
      fixture.destroy();
    });
  });

  describe('kept alive behind an open photo (rendered)', () => {
    const photos = Array.from({ length: 3 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
    }));
    let fixture: ComponentFixture<GalleryComponent>;
    let gallery: GalleryComponent;
    let content: { measureScrollOffset(from: 'top'): number; scrollTo(options: ScrollToOptions): void };
    let scrollTo: Mock;

    beforeEach(() => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.config.set({ features: { show_rating_controls: true } });
      mockStore.photos.set(photos);
      mockStore.total.set(photos.length);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      gallery = fixture.componentInstance;
      // jsdom has no scrollIntoView; stub it per card, never on the prototype.
      for (const host of fixture.nativeElement.querySelectorAll('[data-pidx]') as NodeListOf<HTMLElement>) {
        host.scrollIntoView = () => {};
      }
      content = (gallery as unknown as { scrollContent(): typeof content }).scrollContent();
      // jsdom has no Element.scrollTo.
      scrollTo = vi.spyOn(content, 'scrollTo').mockImplementation(() => {}) as unknown as Mock;
    });

    afterEach(() => {
      fixture.destroy();
      // Spec files share a worker window. Release the queued animation-frame
      // spy here so later navigation suites can restore focus normally.
      vi.restoreAllMocks();
    });

    function openPhoto(index: number): HTMLElement {
      const tile = fixture.nativeElement.querySelector(`[data-pidx="${index}"] [tabindex]`) as HTMLElement;
      tile.focus();
      // Real navigation needs routes this spec does not have; the gallery only listens for the start.
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, `/photo?path=${photos[index].path}`));
      outletMock.detachEvents.next(gallery);
      tile.blur();
      return tile;
    }

    it('does not open a resumed photo after the owning gallery is parked', async () => {
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      let resolveResume!: (path: string) => void;
      mockStore.continueReview.mockImplementation(() => new Promise<string>(resolve => { resolveResume = resolve; }));
      const pending = (gallery as unknown as { continueReview(): Promise<void> }).continueReview();
      openPhoto(0);
      mockStore.photos.set([{ ...photos[1] }]);
      navigate.mockClear();
      resolveResume(photos[1].path);
      await pending;
      expect(navigate).not.toHaveBeenCalled();
    });

    it('does not open a resumed photo after navigation away even before detach', async () => {
      const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
      let resolveResume!: (path: string) => void;
      mockStore.continueReview.mockImplementation(() => new Promise<string>(resolve => { resolveResume = resolve; }));
      const pending = (gallery as unknown as { continueReview(): Promise<void> }).continueReview();
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(2, '/stats'));
      resolveResume(photos[1].path);
      await pending;
      expect(navigate).not.toHaveBeenCalled();
    });

    it('defers the filter sidebar until its block is rendered', async () => {
      expect(fixture.nativeElement.querySelector('mat-sidenav input')).toBeNull();
      const blocks = await fixture.getDeferBlocks();
      expect(blocks).toHaveLength(1);
      await blocks[0].render(DeferBlockState.Complete);
      expect(fixture.nativeElement.querySelector('mat-sidenav input')).not.toBeNull();
    });

    it('cancels pending sidebar searches when the gallery is parked', async () => {
      mockStore.config.set({ features: { show_semantic_search: true } });
      const [sidebarBlock] = await fixture.getDeferBlocks();
      await sidebarBlock.render(DeferBlockState.Complete);
      const sidebar = (fixture.componentInstance as any).filterSidebar() as GalleryFilterSidebarComponent;
      vi.useFakeTimers();
      try {
        const search = fixture.nativeElement.querySelector(`input[placeholder="${I18N.gallery.semantic_search_placeholder}"]`) as HTMLInputElement;
        search.value = 'sunset';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        sidebar.onSearchThresholdChange(30);
        mockStore.updateFilter.mockClear();
        openPhoto(0);
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).not.toHaveBeenCalled();
        expect((sidebar as any).searchThresholdValue()).not.toBe(30);
        expect(search.value).toBe(mockStore.filters().semanticQuery);
      } finally {
        vi.useRealTimers();
      }
    });

    it('preserves the mosaic width while parked and accepts a resize after return', () => {
      let resize!: ResizeObserverCallback;
      const observer = { observe: vi.fn(), disconnect: vi.fn(), unobserve: vi.fn() };
      vi.spyOn(globalThis, 'ResizeObserver').mockImplementation(function (callback) {
        resize = callback;
        return observer;
      });
      (gallery as any).setupResizeObserver();
      const notify = (width: number) => resize([{ contentRect: { width } } as ResizeObserverEntry], observer as ResizeObserver);
      notify(1000);
      const rows = gallery.mosaicRows();
      expect(rows.length).toBeGreaterThan(0);
      openPhoto(0);
      notify(0);
      expect(gallery.mosaicRows()).toBe(rows);
      outletMock.attachEvents.next(gallery);
      notify(800);
      expect(gallery.mosaicRows()).not.toBe(rows);
    });

    it('ignores another gallery being attached and refreshes counts only on its own return', () => {
      openPhoto(0);
      mockStore.loadTypeCounts.mockClear();
      mockStore.loadFilterOptions.mockClear();
      outletMock.attachEvents.next({});
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
      expect(mockStore.loadFilterOptions).not.toHaveBeenCalled();
      expect(mockStore.resumeListingReads).not.toHaveBeenCalled();
      outletMock.attachEvents.next(gallery);
      expect(TestBed.inject(HeaderSlotService).template()).toBeNull();
      expect(mockStore.loadTypeCounts).toHaveBeenCalledOnce();
      expect(mockStore.loadFilterOptions).toHaveBeenCalledOnce();
      expect(mockStore.resumeListingReads).toHaveBeenCalledOnce();
      expect(mockStore.parkListingReads).toHaveBeenCalledOnce();
    });

    it('destroys an active slideshow when the gallery is parked', () => {
      mockStore.slideshowActive.set(true);
      fixture.detectChanges();
      const slideshow = fixture.debugElement.query(By.directive(SlideshowComponent));
      const destroy = vi.fn();
      slideshow.injector.get(DestroyRef).onDestroy(destroy);
      openPhoto(0);
      expect(mockStore.slideshowActive()).toBe(false);
      expect(destroy).toHaveBeenCalledOnce();
    });

    it('keeps collection controls local while help and controls follow gallery parking', () => {
      const header = TestBed.inject(HeaderSlotService);
      expect(header.template()).toBeNull();
      expect(fixture.nativeElement.querySelector('[data-collection-actions]')).not.toBeNull();
      openPhoto(1);
      expect(header.template()).toBeNull();
      outletMock.attachEvents.next(gallery);
      expect(header.template()).toBeNull();
    });

    it('returns to the scroll position and the card the photo was opened from', () => {
      const measure = vi.spyOn(content, 'measureScrollOffset').mockReturnValue(640);
      const tile = openPhoto(1);
      // The Back navigation starts while the gallery is still detached and reads 0.
      measure.mockReturnValue(0);
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(2, '/', 'popstate'));
      outletMock.attachEvents.next(gallery);
      expect(scrollTo).toHaveBeenCalledWith({ top: 640 });
      expect(document.activeElement).toBe(tile);
      expect((gallery as unknown as { activeIndex(): number }).activeIndex()).toBe(1);
    });

    it.each([false, true])('reanchors the opened card after layout drift or a parked resize (resize=%s)', resized => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      let width = 1000;
      let height = 800;
      let scroll = 640;
      let absoluteTop = 740;
      vi.spyOn(viewport, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, width, height } as DOMRect));
      vi.spyOn(host, 'getBoundingClientRect').mockImplementation(() => ({ top: absoluteTop - scroll, height: 200 } as DOMRect));
      vi.spyOn(content, 'measureScrollOffset').mockImplementation(() => scroll);
      scrollTo.mockImplementation(({ top }: ScrollToOptions) => { scroll = top!; });
      for (let cycle = 0; cycle < 2; cycle++) {
        openPhoto(1);
        if (resized) { width = 600; height = 400; }
        absoluteTop += 80;
        outletMock.attachEvents.next(gallery);
        for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
        expect(host.getBoundingClientRect().top).toBe(100);
        expect(document.activeElement?.closest('[data-pidx]')).toBe(host);
      }
    });

    it('focuses the replacement card after the responsive grid recreates its DOM', () => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 0, width: 1000, height: 800 } as DOMRect);
      vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect);
      openPhoto(1);
      outletMock.attachEvents.next(gallery);
      const replacement = host.cloneNode(true) as HTMLElement;
      host.replaceWith(replacement);
      (gallery as any).setCursor(-1);
      vi.spyOn(replacement, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect);
      for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
      expect(document.activeElement?.closest('[data-pidx]')).toBe(replacement);
    });

    it.each(['cursor', 'input', 'escape'] as const)('does not override newer same-gallery %s interaction before the anchor frame', interaction => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 0, width: 1000, height: 800 } as DOMRect);
      vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect);
      openPhoto(1);
      outletMock.attachEvents.next(gallery);
      let focused: HTMLElement;
      if (interaction === 'cursor') {
        (gallery as any).setCursor(2);
        focused = fixture.nativeElement.querySelector('[data-pidx="2"] [tabindex]');
      } else if (interaction === 'escape') {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        (gallery as any).setCursor(-1);
        focused = document.body;
      } else {
        focused = document.createElement('input');
        fixture.nativeElement.append(focused);
      }
      if (interaction === 'escape') (document.activeElement as HTMLElement)?.blur();
      else focused.focus({ preventScroll: true });
      scrollTo.mockClear();
      for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
      expect(document.activeElement).toBe(focused);
      expect(scrollTo).not.toHaveBeenCalled();
    });

    it.each(['wheel', 'touchstart', 'identity'] as const)('cancels the final anchor frame after %s changes', interruption => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 0, width: 1000, height: 800 } as DOMRect);
      const rect = vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect);
      openPhoto(1);
      rect.mockReturnValue({ top: 180, height: 200 } as DOMRect);
      outletMock.attachEvents.next(gallery);
      for (const callback of frames.splice(0)) callback(0);
      const tile = host.querySelector<HTMLElement>('[tabindex]')!;
      const focus = vi.spyOn(tile, 'focus');
      scrollTo.mockClear();
      if (interruption === 'identity') (mockAuth['identity'] as Mock).mockReturnValue('bob');
      else document.dispatchEvent(new Event(interruption, { bubbles: true }));
      for (const callback of frames.splice(0)) callback(0);
      expect(scrollTo).not.toHaveBeenCalled();
      expect(focus).not.toHaveBeenCalled();
    });

    it('does not apply a deferred anchor after another navigation starts', () => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 0, width: 1000, height: 800 } as DOMRect);
      vi.spyOn(host, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect);
      openPhoto(1);
      outletMock.attachEvents.next(gallery);
      scrollTo.mockClear();
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(3, '/stats'));
      for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
      expect(scrollTo).not.toHaveBeenCalled();
    });

    it('closes a gallery menu when the gallery parks', () => {
      mockStore.selectionCount.set(1);
      fixture.detectChanges();
      const trigger = fixture.debugElement.query(By.directive(MatMenuTrigger)).injector.get(MatMenuTrigger);
      trigger.openMenu();
      fixture.detectChanges();
      expect(trigger.menuOpen).toBe(true);
      openPhoto(1);
      expect(trigger.menuOpen).toBe(false);
    });

    it('closes collection settings when the gallery parks', () => {
      const trigger = fixture.nativeElement.querySelector('[data-collection-options] button') as HTMLButtonElement;
      trigger.click(); fixture.detectChanges();
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
      openPhoto(1); fixture.detectChanges();
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
      expect(TestBed.inject(OverlayContainer).getContainerElement().querySelector('[role="dialog"]')).toBeNull();
    });

    it('does not override a pointer press made before the anchor frame', () => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 0, width: 1000, height: 800 } as DOMRect);
      let top = 100;
      vi.spyOn(host, 'getBoundingClientRect').mockImplementation(() => ({ top, height: 200 } as DOMRect));
      openPhoto(1);
      top = 180;
      outletMock.attachEvents.next(gallery);
      // Focus stays on the opened card; only the pointer veto can stop the re-anchor.
      document.dispatchEvent(new Event('pointerdown', { bubbles: true }));
      scrollTo.mockClear();
      for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
      expect(scrollTo).not.toHaveBeenCalled();
    });

    it('clamps a parked-resize anchor so the card stays inside a shorter viewport', () => {
      const frames: FrameRequestCallback[] = [];
      vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return frames.length; });
      const host = fixture.nativeElement.querySelector('[data-pidx="1"]') as HTMLElement;
      const viewport = (content as any).getElementRef().nativeElement as HTMLElement;
      let height = 800;
      let scroll = 640;
      const absoluteTop = 740;
      vi.spyOn(viewport, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, width: 1000, height } as DOMRect));
      vi.spyOn(host, 'getBoundingClientRect').mockImplementation(() => ({ top: absoluteTop - scroll, height: 200 } as DOMRect));
      vi.spyOn(content, 'measureScrollOffset').mockImplementation(() => scroll);
      scrollTo.mockImplementation(({ top }: ScrollToOptions) => { scroll = top!; });
      openPhoto(1);
      height = 250;
      outletMock.attachEvents.next(gallery);
      for (let frame = 0; frame < 3; frame++) for (const callback of frames.splice(0)) callback(0);
      // Anchor offset 100 would push the 200px card past a 250px viewport: clamped to 250 - 200.
      expect(host.getBoundingClientRect().top).toBe(50);
    });

    it('returns to the photo last viewed when the arrows moved off the one opened', () => {
      openPhoto(1);
      const router = TestBed.inject(Router);
      vi.spyOn(router, 'currentNavigation').mockReturnValue({
        previousNavigation: { finalUrl: router.parseUrl(`/photo?path=${encodeURIComponent(photos[2].path)}`) },
      } as unknown as ReturnType<Router['currentNavigation']>);
      outletMock.attachEvents.next(gallery);
      expect((gallery as unknown as { activeIndex(): number }).activeIndex()).toBe(2);
      expect(document.activeElement?.closest('[data-pidx]')?.getAttribute('data-pidx')).toBe('2');
    });

    describe('keyboard cursor', () => {
      const cursor = () => gallery as unknown as {
        activeIndex(): number;
        activePath(): string | null;
        toggleSelection(photo: unknown, event: undefined, index: number): void;
      };
      const tileAt = (index: number) => fixture.nativeElement.querySelector(`[data-pidx="${index}"] [tabindex]`) as HTMLElement;
      const navigationStart = () =>
        (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, '/photo'));

      it('rates the photo that was open, not photo 0, after the focus loss of the detach', () => {
        cursor().toggleSelection(photos[2], undefined, 2);
        const tile = openPhoto(2);
        outletMock.attachEvents.next(gallery);
        fixture.detectChanges();
        expect(cursor().activeIndex()).toBe(2);
        expect(cursor().activePath()).toBe('/p2.jpg');
        expect(document.activeElement).toBe(tile);
        mockStore.setRating.mockClear();
        tile.dispatchEvent(new KeyboardEvent('keydown', { key: '3', bubbles: true }));
        expect(mockStore.setRating).toHaveBeenCalledWith('/p2.jpg', 3);
        expect(mockStore.setRating).not.toHaveBeenCalledWith('/p0.jpg', expect.anything());
      });

      it('restores the cursor when only the focus, not the cursor, was on the card', () => {
        expect(cursor().activeIndex()).toBe(-1);
        openPhoto(2);
        outletMock.attachEvents.next(gallery);
        expect(cursor().activeIndex()).toBe(2);
        expect(cursor().activePath()).toBe('/p2.jpg');
      });

      it('follows the photo when the list changed while parked', () => {
        openPhoto(2);
        mockStore.photos.set([photos[0], photos[2]]);
        outletMock.attachEvents.next(gallery);
        expect(cursor().activeIndex()).toBe(1);
        expect(cursor().activePath()).toBe('/p2.jpg');
      });

      it('leaves no cursor and no stale card focused when the photo was removed while parked', () => {
        cursor().toggleSelection(photos[2], undefined, 2);
        const tile = openPhoto(2);
        mockStore.photos.set([photos[0], photos[1]]);
        expect(() => outletMock.attachEvents.next(gallery)).not.toThrow();
        expect(cursor().activeIndex()).toBe(-1);
        expect(document.activeElement).not.toBe(tile);
      });

      it('gives the same result when the focus is lost before the detach event', () => {
        cursor().toggleSelection(photos[2], undefined, 2);
        const tile = tileAt(2);
        navigationStart();
        tile.blur();
        outletMock.detachEvents.next(gallery);
        outletMock.attachEvents.next(gallery);
        expect(cursor().activeIndex()).toBe(2);
        expect(cursor().activePath()).toBe('/p2.jpg');
      });

      it('puts the focus back on the cursor card when the focus was not on a card', () => {
        cursor().toggleSelection(photos[2], undefined, 2);
        const bar = document.createElement('div');
        bar.setAttribute('data-selection-bar', '');
        const button = document.createElement('button');
        bar.appendChild(button);
        document.body.appendChild(bar);
        button.focus();
        expect(cursor().activeIndex()).toBe(2);
        navigationStart();
        outletMock.detachEvents.next(gallery);
        bar.remove();
        outletMock.attachEvents.next(gallery);
        expect(cursor().activeIndex()).toBe(2);
        expect(document.activeElement).toBe(tileAt(2));
      });
    });

    describe('tooltips', () => {
      const overlay = () => TestBed.inject(OverlayContainer).getContainerElement();
      const settle = () => new Promise(resolve => setTimeout(resolve, 30));
      const tooltipsOf = (root: DebugElement) => root.queryAll(By.directive(MatTooltip)).map(d => d.injector.get(MatTooltip));

      async function expectParkHides(tooltip: MatTooltip): Promise<void> {
        tooltip.show(0);
        await settle();
        expect(overlay().querySelector('.mat-mdc-tooltip')).not.toBeNull();
        outletMock.detachEvents.next(gallery);
        await settle();
        expect(overlay().querySelector('.mat-mdc-tooltip')).toBeNull();
        expect(tooltip._isTooltipVisible()).toBe(false);
        const seen = vi.fn();
        document.addEventListener('keydown', seen);
        try {
          document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
        } finally {
          document.removeEventListener('keydown', seen);
        }
        expect(seen).toHaveBeenCalledOnce();
      }

      it('hides a card tooltip when the gallery is parked', async () => {
        const card = fixture.debugElement.query(By.directive(PhotoCardComponent));
        await expectParkHides(tooltipsOf(card)[0]);
      });

      it('hides a tooltip of the gallery\'s own template when the gallery is parked', async () => {
        mockStore.selectionCount.set(1);
        mockStore.selectedPaths.set(new Set(['/p0.jpg']));
        fixture.detectChanges();
        const own = fixture.debugElement.queryAll(By.directive(MatTooltip))
          .filter(d => !d.nativeElement.closest('app-photo-card'))
          .map(d => d.injector.get(MatTooltip));
        expect(own.length).toBeGreaterThan(0);
        await expectParkHides(own[0]);
      });

      it('hides a filter sidebar tooltip when the gallery is parked', async () => {
        const [sidebarBlock] = await fixture.getDeferBlocks();
        await sidebarBlock.render(DeferBlockState.Complete);
        const sidebar = fixture.debugElement.query(By.css('mat-sidenav'));
        await expectParkHides(tooltipsOf(sidebar)[0]);
      });
    });

    it('hands the page help back while a photo is open, and takes it again only on its own return', () => {
      const help = TestBed.inject(PageHelpService);
      expect(help.descriptionKey()).toBe(I18N.gallery.help);
      openPhoto(0);
      expect(help.descriptionKey()).toBeNull();
      outletMock.attachEvents.next({});
      expect(help.descriptionKey()).toBeNull();
      outletMock.attachEvents.next(gallery);
      expect(help.descriptionKey()).toBe(I18N.gallery.help);
    });

    it('drops a hover tooltip photo left behind while parked', () => {
      const state = gallery as unknown as { tooltipPhoto: WritableSignal<unknown> };
      openPhoto(0);
      state.tooltipPhoto.set(photos[1]);
      outletMock.attachEvents.next(gallery);
      expect(state.tooltipPhoto()).toBeNull();
    });

    it('ignores Ctrl+A while parked, so the photo page cannot select the hidden grid', () => {
      const ctrlA = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', ctrlKey: true }));
      openPhoto(0);
      ctrlA();
      expect(mockStore.selectAll).not.toHaveBeenCalled();
      outletMock.attachEvents.next(gallery);
      ctrlA();
      expect(mockStore.selectAll).toHaveBeenCalledOnce();
    });

    it('snapshots the opening scroll position when a parked gallery is destroyed', () => {
      const measure = vi.spyOn(content, 'measureScrollOffset').mockReturnValue(640);
      openPhoto(1);
      // Detached, the viewport reads 0.
      measure.mockReturnValue(0);
      fixture.destroy();
      expect((mockStore.viewSnapshot() as { scrollTop: number } | null)?.scrollTop).toBe(640);
    });

    it('ignores another gallery being detached', () => {
      mockStore.parkListingReads.mockClear();
      outletMock.detachEvents.next({});
      expect(mockStore.parkListingReads).not.toHaveBeenCalled();
      expect(fixture.nativeElement.querySelector('[data-collection-actions]')).not.toBeNull();
    });
  });

  describe('toolbar search and view shortcuts (rendered)', () => {
    // Independent overlays exercise shortcut guards beside the real collection controls.
    @Component({
      selector: 'app-toolbar-host',
      imports: [MatMenuModule, MatSelectModule],
      template: `
        <button data-testid="keyboard-test-menu" [matMenuTriggerFor]="menu">Menu</button>
        <mat-menu #menu="matMenu">
          <button mat-menu-item>Berries</button>
          <button mat-menu-item>Violet</button>
          <button mat-menu-item>/ Slash</button>
        </mat-menu>
        <mat-select aria-label="Test selector">
          <mat-option value="b">Berries</mat-option>
          <mat-option value="v">Violet</mat-option>
          <mat-option value="s">/ Slash</mat-option>
        </mat-select>
      `,
    })
    class ToolbarHostComponent {

    }

    let fixture: ComponentFixture<GalleryComponent>;
    let host: ComponentFixture<ToolbarHostComponent>;
    let gallery: GalleryComponent;
    let search: HTMLInputElement;

    beforeEach(() => {
      mockStore.setGalleryMode = vi.fn();
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      gallery = fixture.componentInstance;
      host = TestBed.createComponent(ToolbarHostComponent);
      host.detectChanges();
      document.body.appendChild(host.nativeElement);
      document.body.appendChild(fixture.nativeElement);
      search = fixture.nativeElement.querySelector(`input[type="search"]`) as HTMLInputElement;
      mockStore.updateFilter.mockClear();
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
      (fixture.nativeElement as HTMLElement).remove();
      host.destroy();
      (host.nativeElement as HTMLElement).remove();
      if (!fixture.componentRef.hostView.destroyed) fixture.destroy();
    });

    function type(value: string): void {
      search.value = value;
      search.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function key(init: KeyboardEventInit, target: EventTarget = document): KeyboardEvent {
      const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event;
    }

    describe('suggested stack scope', () => {
      const edition = signal(true);

      function dialogForSuggestions(): MatDialog {
        const dialog = (gallery as unknown as { dialog: MatDialog }).dialog;
        vi.spyOn(dialog, 'openDialogs', 'get').mockReturnValue([]);
        vi.spyOn(dialog, 'open').mockReturnValue({} as ReturnType<MatDialog['open']>);
        return dialog;
      }

      beforeEach(() => {
        mockStore.filterPayload.mockImplementation(() => GalleryStore.prototype.filterPayload.call(mockStore));
        (mockAuth as { isEdition: unknown }).isEdition = () => edition();
        edition.set(true);
        fixture.detectChanges();
        host.detectChanges();
      });

      it('withholds discovery and refuses direct launch without edition rights', async () => {
        edition.set(false);
        fixture.detectChanges();
        host.detectChanges();
        expect(fixture.nativeElement.querySelector('[data-stack-suggestions]')).toBeNull();
        const dialog = dialogForSuggestions();
        await (gallery as unknown as { openStackSuggestions(): Promise<void> }).openStackSuggestions();
        expect(dialog.open).not.toHaveBeenCalled();
      });

      it.each([
        { similar_to: '/visible/source.jpg' },
        { semanticQuery: 'photos of mountains' },
      ])('withholds discovery and refuses direct launch for %j', async search => {
        mockStore.filters.set({ ...DEFAULT_FILTERS, ...search });
        mockStore.canScopeSelectionToView.set(false);
        fixture.detectChanges();
        host.detectChanges();
        expect(mockStore.filterPayload()).toBeNull();
        expect(fixture.nativeElement.querySelector('[data-stack-suggestions]')).toBeNull();
        const dialog = dialogForSuggestions();
        await (gallery as unknown as { openStackSuggestions(): Promise<void> }).openStackSuggestions();
        expect(dialog.open).not.toHaveBeenCalled();
      });

      it('navigates from the toolbar with the exact filter payload and opaque return URL', async () => {
        mockStore.filters.set({ ...DEFAULT_FILTERS, album_id: '42', camera: 'Camera & Lens' });
        const filters = mockStore.filterPayload();
        expect(filters).toMatchObject({ album_id: '42', camera: 'Camera & Lens' });
        const router = TestBed.inject(Router);
        const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
        vi.spyOn(router, 'url', 'get').mockReturnValue('/album/42?sort=date&tag=a%20b#focused');
        fixture.nativeElement.querySelector('[data-collection-review] button').click(); fixture.detectChanges();
        const button = TestBed.inject(OverlayContainer).getContainerElement().querySelector('[data-stack-suggestions]') as HTMLButtonElement;
        button.click();
        expect(navigate).toHaveBeenCalledWith(['/culling'], { queryParams: {
          mode: 'stacks', filters: JSON.stringify(filters), return: '/album/42?sort=date&tag=a%20b#focused',
        } });
      });

    });

    describe('search delay', () => {
      it('filters 400 ms after the last keystroke, not before', () => {
        type('cat');
        vi.advanceTimersByTime(399);
        expect(mockStore.updateFilter).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('search', 'cat');
      });

      it('restarts the delay on every keystroke', () => {
        type('ca');
        vi.advanceTimersByTime(300);
        type('cat');
        vi.advanceTimersByTime(300);
        expect(mockStore.updateFilter).not.toHaveBeenCalled();
        vi.advanceTimersByTime(100);
        expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('search', 'cat');
      });

      it('Enter commits at once and cancels the pending timer', () => {
        type('cat');
        search.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
        expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('search', 'cat');
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).toHaveBeenCalledOnce();
      });

      it('leaving the box commits the pending text at once, so a click away does not lose it', () => {
        type('cat');
        search.dispatchEvent(new FocusEvent('blur'));
        expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('search', 'cat');
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).toHaveBeenCalledOnce();
      });

      it('never fires once the gallery is parked behind a photo page', () => {
        type('cat');
        outletMock.detachEvents.next(gallery);
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).not.toHaveBeenCalled();
      });

      it('never fires once the gallery is destroyed', () => {
        type('cat');
        fixture.destroy();
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).not.toHaveBeenCalled();
      });

      it('clearing the box cancels a pending search, so the typed text does not come back', () => {
        mockStore.filters.set({ ...DEFAULT_FILTERS, search: 'dog' });
        type('dogs');
        (gallery as unknown as { clearSearch(): void }).clearSearch();
        vi.advanceTimersByTime(400);
        expect(mockStore.updateFilter).toHaveBeenCalledExactlyOnceWith('search', '');
      });
    });

    describe('/, B and V', () => {
      const stubWide = (matches: boolean) => {
        Object.defineProperty(gallery, 'isDesktop', { value: signal(matches), configurable: true });
        (gallery as unknown as { containerWidth: WritableSignal<number> }).containerWidth.set(matches ? 1280 : 375);
        fixture.detectChanges();
      };
      afterEach(() => {
        vi.unstubAllGlobals();
        TestBed.inject(KeyboardMappingService).resetAll();
        localStorage.removeItem(KEYMAP_STORAGE_KEY);
      });

      it('/ focuses and selects the toolbar search', () => {
        stubWide(true);
        search.value = 'cat';
        const event = key({ key: '/' });
        expect(event.defaultPrevented).toBe(true);
        fixture.detectChanges(); TestBed.tick();
        expect(document.activeElement).toBe(search);
        expect(search.selectionStart).toBe(0);
        expect(search.selectionEnd).toBe(3);
        expect((gallery as unknown as { mobileSearchOpen: () => boolean }).mobileSearchOpen()).toBe(false);
      });

      it('/ focuses the collection search on narrow screens without opening another panel', () => {
        stubWide(false);
        expect(key({ key: '/' }).defaultPrevented).toBe(true);
        fixture.detectChanges(); TestBed.tick();
        expect(document.activeElement).toBe(search);
        expect((gallery as unknown as { mobileSearchOpen: () => boolean }).mobileSearchOpen()).toBe(true);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
      });

      it.each(['b', 'B'])('%s toggles the filter sidebar', k => {
        mockStore.filterDrawerOpen.set(false);
        expect(key({ key: k }).defaultPrevented).toBe(true);
        expect(mockStore.setFilterDrawerOpen).toHaveBeenCalledWith(true);
        mockStore.filterDrawerOpen.set(true);
        key({ key: k });
        expect(mockStore.setFilterDrawerOpen).toHaveBeenLastCalledWith(false);
      });

      it.each(['v', 'V'])('%s cycles grid, mosaic and metadata list', k => {
        (gallery as unknown as { containerWidth: WritableSignal<number> }).containerWidth.set(800);
        mockStore.galleryMode.set('mosaic');
        expect(key({ key: k }).defaultPrevented).toBe(true);
        expect(mockStore.setGalleryMode).toHaveBeenCalledWith('list');
        mockStore.galleryMode.set('list');
        key({ key: k });
        expect(mockStore.setGalleryMode).toHaveBeenLastCalledWith('grid');
        mockStore.galleryMode.set('grid');
        key({ key: k });
        expect(mockStore.setGalleryMode).toHaveBeenLastCalledWith('mosaic');
      });

      it('leaves other keys alone', () => {
        expect(key({ key: 'q' }).defaultPrevented).toBe(false);
      });

      it('toggles the sidebar with a remapped key, and no longer with B', () => {
        TestBed.inject(KeyboardMappingService).setKey('toggleSidebar', 'w');
        mockStore.filterDrawerOpen.set(false);
        expect(key({ key: 'w' }).defaultPrevented).toBe(true);
        expect(mockStore.setFilterDrawerOpen).toHaveBeenCalledWith(true);
        const drawer = mockStore.setFilterDrawerOpen as unknown as ReturnType<typeof vi.fn>;
        drawer.mockClear();
        key({ key: 'b' });
        expect(drawer).not.toHaveBeenCalled();
      });

      it('focuses the search with a remapped key, and no longer with /', () => {
        stubWide(true);
        TestBed.inject(KeyboardMappingService).setKey('focusSearch', 'g');
        expect(key({ key: 'g' }).defaultPrevented).toBe(true);
        fixture.detectChanges(); TestBed.tick();
        expect(document.activeElement).toBe(search);
        search.blur();
        expect(key({ key: '/' }).defaultPrevented).toBe(false);
        expect(document.activeElement).not.toBe(search);
      });

      it('flips the layout with a remapped key, and no longer with V', () => {
        TestBed.inject(KeyboardMappingService).setKey('swapLayout', 'l');
        (gallery as unknown as { containerWidth: WritableSignal<number> }).containerWidth.set(800);
        mockStore.galleryMode.set('mosaic');
        expect(key({ key: 'l' }).defaultPrevented).toBe(true);
        expect(mockStore.setGalleryMode).toHaveBeenCalledWith('list');
        const mode = mockStore.setGalleryMode as unknown as ReturnType<typeof vi.fn>;
        mode.mockClear();
        key({ key: 'v' });
        expect(mode).not.toHaveBeenCalled();
      });

      it('does nothing while the gallery is parked behind a photo page', () => {
        outletMock.detachEvents.next(gallery);
        for (const k of ['/', 'b', 'v']) expect(key({ key: k }).defaultPrevented).toBe(false);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
      });

      it('does nothing while typing in a field', () => {
        const input = document.createElement('input');
        document.body.appendChild(input);
        try {
          for (const k of ['/', 'b', 'v']) expect(key({ key: k }, input).defaultPrevented).toBe(false);
          expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
          expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
        } finally {
          input.remove();
        }
      });

      it.each([['ctrlKey'], ['metaKey'], ['altKey']])('does nothing with %s held', mod => {
        expect(key({ key: 'b', [mod]: true }).defaultPrevented).toBe(false);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
      });

      it('does nothing while the slideshow is open', () => {
        mockStore.slideshowActive.set(true);
        for (const k of ['/', 'b', 'v']) expect(key({ key: k }).defaultPrevented).toBe(false);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
        expect(document.activeElement).not.toBe(search);
      });

      it.each(['b', 'v', '/'])('leaves %s to an open Material menu', async letter => {
        vi.useRealTimers();
        const trigger = host.debugElement.query(By.css('[data-testid="keyboard-test-menu"]')).injector.get(MatMenuTrigger);
        trigger.openMenu();
        fixture.detectChanges();
        host.detectChanges();
        await host.whenStable();
        const menu = TestBed.inject(OverlayContainer).getContainerElement().querySelector('[role="menu"]')!;
        const item = menu.querySelector('button')!;
        item.focus();
        vi.useFakeTimers();
        key({ key: letter, keyCode: letter === '/' ? 191 : letter.toUpperCase().charCodeAt(0) }, item);
        vi.runOnlyPendingTimers();
        fixture.detectChanges();
        host.detectChanges();
        expect(trigger.menuOpen).toBe(true);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
        expect(document.activeElement?.textContent?.trim()).toBe(letter === 'b' ? 'Berries' : letter === 'v' ? 'Violet' : '/ Slash');
        trigger.closeMenu();
      });

      it.each(['b', 'v', '/'])('leaves %s to an open Material select', async letter => {
        vi.useRealTimers();
        const select = host.debugElement.query(By.css('mat-select[aria-label="Test selector"]')).componentInstance as MatSelect;
        select.open();
        fixture.detectChanges();
        host.detectChanges();
        await host.whenStable();
        expect(select.panelOpen).toBe(true);
        const panel = select.panel.nativeElement as HTMLElement;
        panel.focus();
        vi.useFakeTimers();
        key({ key: letter, keyCode: letter === '/' ? 191 : letter.toUpperCase().charCodeAt(0) }, panel);
        vi.runOnlyPendingTimers();
        fixture.detectChanges();
        host.detectChanges();
        expect(select.panelOpen).toBe(true);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
        expect(document.activeElement).not.toBe(search);
        const active = document.getElementById((host.debugElement.query(By.css('mat-select[aria-label="Test selector"]')).nativeElement as HTMLElement).getAttribute('aria-activedescendant') ?? '');
        expect(active?.textContent?.trim()).toBe(letter === 'b' ? 'Berries' : letter === 'v' ? 'Violet' : '/ Slash');
        select.close();
      });

      it.each(['b', 'v', '/'])('leaves %s to a focused closed Material select', letter => {
        const debug = host.debugElement.query(By.css('mat-select[aria-label="Test selector"]'));
        const select = debug.componentInstance as MatSelect;
        const element = debug.nativeElement as HTMLElement;
        element.focus();
        key({ key: letter, keyCode: letter === '/' ? 191 : letter.toUpperCase().charCodeAt(0) }, element);
        vi.runOnlyPendingTimers();
        fixture.detectChanges();
        host.detectChanges();
        expect(select.panelOpen).toBe(false);
        expect(select.value).toBe(letter === '/' ? 's' : letter);
        expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        expect(mockStore.setGalleryMode).not.toHaveBeenCalled();
        expect(document.activeElement).toBe(element);
      });

      it('does nothing while a dialog is open', () => {
        const dialog = document.createElement('mat-dialog-container');
        document.body.appendChild(dialog);
        try {
          expect(key({ key: 'b' }).defaultPrevented).toBe(false);
          expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
        } finally {
          dialog.remove();
        }
      });
    });
  });
});
