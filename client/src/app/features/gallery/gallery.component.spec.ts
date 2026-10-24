import type { Mock } from 'vitest';
import { ComponentFixture, DeferBlockState, TestBed } from '@angular/core/testing';
import { ChangeDetectorRef, computed, DebugElement, DestroyRef, signal, TemplateRef, WritableSignal } from '@angular/core';
import { ActivatedRoute, Event as RouterEvent, NavigationStart, Router, RouterOutlet } from '@angular/router';
import { By } from '@angular/platform-browser';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { GalleryPhotoMenuComponent } from './gallery-photo-menu.component';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject, of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatTooltip } from '@angular/material/tooltip';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatSidenav, MatSidenavContainer, MatSidenavContent } from '@angular/material/sidenav';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { buildApiParams, DISPLAY_OPTIONS_KEY } from './gallery-filters.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { GalleryComponent } from './gallery.component';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { SlideshowComponent } from './slideshow.component';
import { I18N } from '../../core/i18n/keys';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';
import { MAX_COMPARE_PANES } from './synced-zoom.component';
import { gridColumnCount } from './gallery-rows.util';
import { ScanService } from '../../core/services/scan.service';
import { UndoService } from '../../core/services/undo.service';
import { SequenceKind } from '../../core/services/sequence-override.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { PageHelpService } from '../../core/services/page-help.service';

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
      loading: signal(false),
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
      currentAlbum: signal(null),
      initializing: signal(false),
      galleryMounts: signal(0),
      galleryMode: signal('mosaic'),
      cardWidth: signal(300),
      virtualScroll: signal(false),
      setFilterDrawerOpen: vi.fn(),
      loadConfig: vi.fn(() => Promise.resolve()),
      loadFilterOptions: vi.fn(() => Promise.resolve()),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
      loadPhotos: vi.fn(() => Promise.resolve()),
      reloadPhotos: vi.fn(() => Promise.resolve()),
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
      viewSnapshot: signal(null),
      pinnedPaths: signal<string[] | null>(null),
      clearPinned: vi.fn(() => Promise.resolve()),
      filterKey: vi.fn((f?: GalleryFilters) => JSON.stringify(buildApiParams(f ?? mockStore.filters(), false, undefined))),
      hiddenSummary: signal({ total: 0, blinks: 0, bursts: 0, duplicates: 0 }),
      hiddenFiltersStash: signal(null),
      showAllHidden: vi.fn(),
      restoreHidden: vi.fn(),
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
      gpsLocationName: signal(''),
      viewFilterParams: signal({}),
    };

    mockApi = {
      thumbnailUrl: vi.fn((path: string) => `/thumbnail?path=${path}`),
      post: vi.fn(() => of({ success: true, overridden: 0, skipped: 0, kind: null })),
      downloadUrl: vi.fn((path: string) => `/download?path=${path}`),
      getRaw: vi.fn(() => of(new Blob(['x']))),
    };

    mockAuth = {
      identity: vi.fn(() => '0|'),
      status: signal({ user_id: 'alice', edition_authenticated: true }),
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

    it('sets the star rating and advances on digit keys', () => {
      fire(keyEvent('3'));
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 3);
      expect(activeIndex()).toBe(1);
    });

    it('rejects and advances on X', () => {
      fire(keyEvent('x'));
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(1);
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

      it('follows a cursor the rate-and-advance keys left behind', () => {
        click({ path: '/a.jpg' }, 0);
        press('3');
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

      await (component as unknown as { batchFavorite(): Promise<void> }).batchFavorite();

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
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function render(mode: 'grid' | 'mosaic', virtual: boolean): HTMLElement[] {
      mockStore.photos.set(photos);
      mockStore.config.set({ features: { show_rating_controls: true } });
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

        (fixture!.nativeElement.querySelector('[role="grid"]') as HTMLElement)
          .dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
        fixture!.detectChanges();

        expect(markedCard(cards)).toBe(-1);
      });
    }
  });

  describe('ngOnInit()', () => {
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
        return Promise.resolve();
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
        return Promise.resolve();
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
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });
      routeMock.snapshot.queryParams = {
        date_from: '2026-01-01', date_to: '2026-01-01', sort: 'date_taken', sort_direction: 'DESC',
      };

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('restores the previous view when the URL matches the snapshot', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
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
        mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });
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

  describe('assistant-pinned list', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    it('keeps the pin when the gallery is restored from a /photo round trip', async () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });

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
      const tpl = (fixture!.componentInstance as unknown as { galleryToolbar(): TemplateRef<unknown> }).galleryToolbar();
      const view = tpl.createEmbeddedView({});
      view.detectChanges();
      const host = document.createElement('div');
      view.rootNodes.forEach((n: Node) => host.appendChild(n));
      return host;
    }
    const hasTypeAndSearch = (host: HTMLElement) =>
      host.textContent?.includes(I18N.ui.filters.type) === true
      && !!host.querySelector(`input[placeholder="${I18N.gallery.search_placeholder}"]`);

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
      expect(hasTypeAndSearch(toolbarView())).toBe(false);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(hasTypeAndSearch(toolbarView())).toBe(true);
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
      const chip = (fixture.nativeElement as HTMLElement).querySelector('[role="status"]')!;
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
    const RENDER_MIGRATION_KEY = 'facet_render_migration_dismissed';

    function rebuild(): GalleryComponent {
      return TestBed.runInInjectionContext(() => new GalleryComponent());
    }

    beforeEach(() => {
      localStorage.removeItem(RENDER_MIGRATION_KEY);
      component = rebuild();
    });

    afterEach(() => localStorage.removeItem(RENDER_MIGRATION_KEY));

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

    it('hides on dismiss and stays hidden for the next visit', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      component.dismissRenderMigration();

      expect(component.showRenderMigrationBanner()).toBe(false);
      expect(localStorage.getItem(RENDER_MIGRATION_KEY)).toBe('true');

      // A migration takes hours, so a reload must not raise the notice again.
      const reloaded = rebuild();
      expect(reloaded.showRenderMigrationBanner()).toBe(false);
    });
  });

  describe('floating advisory notices', () => {
    function render(): HTMLElement {
      const fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }
    const stack = (html: HTMLElement) => html.querySelector<HTMLElement>('[data-gallery-notices]');
    const button = (html: HTMLElement, label: string) =>
      Array.from(html.querySelectorAll('button')).find(b => b.textContent?.includes(label));

    beforeEach(() => {
      localStorage.removeItem('facet_render_migration_dismissed');
      mockStore.hiddenSummary.set({ total: 6, blinks: 0, bursts: 4, duplicates: 0, brackets: 2, panoramas: 0 });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_bursts: true });
    });

    afterEach(() => localStorage.removeItem('facet_render_migration_dismissed'));

    it('renders the hidden-photos notice in the stack, outside the scrolling content, and Show all acts', () => {
      const html = render();
      const notices = stack(html);
      expect(notices).toBeTruthy();
      expect(notices!.closest('mat-sidenav-content')).toBeNull();
      expect(notices!.querySelector('[role="status"]')?.textContent).toContain(I18N.gallery.hidden_banner.message);
      button(html, I18N.gallery.hidden_banner.show_all)?.click();
      expect(mockStore.showAllHidden).toHaveBeenCalled();
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

    it('stacks the migration notice below the hidden notice and Dismiss removes only it', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      const html = render();
      const cards = Array.from(stack(html)!.querySelectorAll('[role="status"]'));
      expect(cards).toHaveLength(2);
      expect(cards[0].textContent).toContain(I18N.gallery.hidden_banner.message);
      expect(cards[1].textContent).toContain(I18N.gallery.render_migration.message);
      button(html, I18N.ui.buttons.dismiss)?.click();
      expect(localStorage.getItem('facet_render_migration_dismissed')).toBe('true');
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
        const notices = stack(render())!;
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

      describe('while a photo is current', () => {
        const a = { path: '/a.jpg' };
        const b = { path: '/b.jpg' };
        const panelPhoto = () => (component as unknown as { panelPhoto(): unknown }).panelPhoto();
        const release = () => (component as unknown as { releasePanel(): void }).releasePanel();

        beforeEach(() => {
          mockStore.photos.set([a, b]);
          click(a, 0);
          component.showTooltip(hoverEvent, a as never);
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

      it('disableClose follows the rail: false while the filters occupy the drawer', () => {
        const fixture = TestBed.createComponent(GalleryComponent);
        (fixture.componentInstance as unknown as { railWide: { setup(): void } }).railWide.setup();
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

        it('Escape releases the photo and the drawer is not closed (rendered)', () => {
          // MatDrawer closes itself on an Escape from inside it unless disableClose is set;
          // the open/close effect would then reopen it, so the rail would flicker.
          const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
          const close = vi.spyOn(drawer, 'close');
          escape(rail);
          fixture.detectChanges();
          expect(instance.hasActivePhoto()).toBe(false);
          expect(close).not.toHaveBeenCalled();
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

        it('Escape on the focused Deselect button leaves focus on the rail', () => {
          document.body.appendChild(fixture.nativeElement);
          const button = rail.querySelector('button') as HTMLElement;
          button.focus();
          escape(button);
          fixture.detectChanges();
          expect(document.activeElement).toBe(rail);
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

  describe('compare selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog itself is covered by its own spec; this is the wiring — which
    // photos it is handed, in which order, and when the action is offered.
    it('is offered from two photos up to the pane limit', () => {
      const c = component as unknown as { canCompareSelection: () => boolean };
      for (const n of [0, 1]) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(false);
      }
      for (let n = 2; n <= MAX_COMPARE_PANES; n++) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(true);
      }
      select(Array.from({ length: MAX_COMPARE_PANES + 1 }, (_, i) => `/p${i}.jpg`));
      expect(c.canCompareSelection()).toBe(false);
    });

    it('hands over the grid order, not the order they were picked in', async () => {
      mockStore.photos.set(['/a.jpg', '/b.jpg', '/c.jpg'].map(photo));
      select(['/c.jpg', '/a.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.photos.map((p: { path: string }) => p.path)).toEqual(['/a.jpg', '/c.jpg']);
    });

    it('caps the panes even if more photos are somehow selected', async () => {
      const paths = Array.from({ length: MAX_COMPARE_PANES + 2 }, (_, i) => `/p${i}.jpg`);
      mockStore.photos.set(paths.map(photo));
      select(paths);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect((dialog.open as Mock).mock.calls[0][1].data.photos.length).toBe(MAX_COMPARE_PANES);
    });

    it('does nothing when fewer than two selected photos are loaded', async () => {
      mockStore.photos.set([photo('/a.jpg')]);
      select(['/a.jpg', '/gone.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect(dialog.open).not.toHaveBeenCalled();
    });
  });

  describe('openCullDialog', () => {
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

      await component.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(true);
      expect(data.allowTrash).toBe(true);
    });

    it('passes allowTrash true but trashAvailable false when the package is missing', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: false } });
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(false);
      expect(data.allowTrash).toBe(true);
    });

    it('fails closed to both false when the config has no cull key at all', async () => {
      mockStore.config.set({});
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

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

      await component.openCullDialog();

      expect(order).toEqual(['load', 'clear']);
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

      await component.openCullDialog();

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
      const task = component.openCaptureDateDialog();
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
      const pending = component.openCaptureDateDialog();
      mockStore.filterPayload.mockReturnValue({ camera: 'Nikon' });
      mockStore.excludedPaths.set(new Set(['/new.jpg']));
      await pending;
      expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: [], filters: { camera: 'Canon' }, exclude: ['/skip.jpg'], count: 12 });
    });
  });

  describe('openBatchGpsDialog', () => {
    it.each(['identity', 'edition', 'navigation', 'destroy'])('does not open after lazy GPS launch loses %s', async loss => {
      mockAuth['isEdition'] = vi.fn(() => true);
      mockStore.selectedPaths.set(new Set(['/a'])); mockStore.selectionCount.set(1);
      const dialog = TestBed.inject(MatDialog);
      const task = component.openBatchGpsDialog();
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
      const pending = component.openBatchGpsDialog();
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
      await component.openBatchGpsDialog();
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
      await component.openBatchGpsDialog();
      expect(dialog.open).not.toHaveBeenCalled();
      mockAuth['isEdition'] = vi.fn(() => true);
      await component.openBatchGpsDialog();
      expect((dialog.open as Mock).mock.calls[0][1].data.batch).toEqual({ photo_paths: ['/a.jpg', '/b.jpg'] });
    });
  });

  describe('openManualTagsDialog', () => {
    const open = () => (component as unknown as { openManualTagsDialog(): Promise<void> }).openManualTagsDialog();
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog owns its request (its own spec); this is the wiring.
    it('opens the manual-tags dialog with the selected paths', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      expect(dialog.open).toHaveBeenCalledTimes(1);
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.paths).toEqual(['/a.jpg', '/b.jpg']);
      expect(data.filters).toBeNull();
      expect(data.count).toBe(2);
    });

    it('sends the filter and exclusions under view scope', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.filters).toEqual({ page: '1' });
      expect(data.exclude).toEqual(['/skip.jpg']);
      expect(data.count).toBe(650);
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
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(1) });

      await open();

      expect(mockStore.reloadPhotos).toHaveBeenCalledTimes(1);
      expect(mockStore.restoreSelection).toHaveBeenCalledWith(['/a.jpg']);
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
      return f.nativeElement.querySelector(`[data-selection-bar] button[aria-label="${I18N.gallery.selection.edit_tags}"]`);
    }

    it('is a desktop-only button for an edition user', () => {
      const button = tagsButton(render(true));

      expect(button).not.toBeNull();
      expect(button!.closest('.max-md\\:hidden')).not.toBeNull();
    });

    it('is absent without edition', () => {
      expect(tagsButton(render(false))).toBeNull();
    });

    it('opens the dialog when clicked', () => {
      const f = render(true);
      const open = vi.spyOn(f.componentInstance as unknown as { openManualTagsDialog(): Promise<void> }, 'openManualTagsDialog')
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
      not_visible: string[]; sequence_siblings: string[]; skipped: string[];
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

      await component.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('does nothing with an empty selection', async () => {
      select([]);
      const dialog = TestBed.inject(MatDialog);

      await component.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('opens the dialog with paths only (never filters/exclude) and hasCompanion always offered', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

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

      await component.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(true);
    });

    it('passes hasSiblings false when no selected photo carries a bracket/panorama/hdr_panorama sequence_kind', async () => {
      mockStore.photos.set([{ path: '/a.jpg', sequence_kind: null }]);
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(false);
    });

    it('cancelling the dialog makes no request', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

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

      await component.deleteSelected();

      expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', {
        paths: ['/a.jpg', '/b.jpg'],
        include_companions: false,
        include_sequence_siblings: false,
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

      await component.deleteSelected();

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

      await component.deleteSelected();

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
      await component.deleteSelected();

      // Asserted on the i18n mock's own call args, not on the snackbar's
      // resolved text: `mockI18n.t` ignores its `vars` argument and echoes
      // the key back, so `snackBar.open`'s first argument is identical
      // ("cull.delete_partial_result") whether `failed` is computed from all
      // four buckets or from `refused_bracket_lead` alone -- asserting on
      // that resolved string would pass under either implementation.
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.cull.delete_partial_result, { deleted: 1, failed: 3 });
    });

    it('a failed request does not touch the store', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));

      await component.deleteSelected();

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
      return f.nativeElement.querySelector('[data-selection-bar] button[aria-label="cull.delete_action"]');
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
    });

    it('is disabled under a view-scoped ("select all in view") selection, with a tooltip explaining why', () => {
      const f = render(true, true);
      const button = deleteButton(f);
      expect(button).not.toBeNull();
      // disabledInteractive: aria-disabled instead of the native attribute, so the tooltip still shows.
      expect(button!.getAttribute('aria-disabled')).toBe('true');
      const tooltipDebug = f.debugElement.queryAll(By.directive(MatTooltip))
        .find(de => de.nativeElement === button);
      expect(tooltipDebug?.injector.get(MatTooltip).message).toBe(I18N.cull.delete_disabled_view_scope_tooltip);
    });
  });

  // The selection bar is a floating, icon-only card inside the gallery host (not a
  // fixed full-width strip): placement, label reachability and the notice baseline.
  describe('floating selection card (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    });

    function render(opts: { edition?: boolean; desktop?: boolean; viewScoped?: boolean; profiles?: string[] } = {}): ComponentFixture<GalleryComponent> {
      const { edition = true, desktop = true, viewScoped = false, profiles = [] } = opts;
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: desktop && media.includes('min-width: 768px'), media, addEventListener() {}, removeEventListener() {},
      }));
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => edition);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => profiles);
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true }, features: { show_albums: true } });
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
      expect(el.classList.contains('rounded-2xl')).toBe(true);
      expect(el.classList.contains('fixed')).toBe(false);
      expect(el.classList.contains('left-2')).toBe(true);
      expect(el.classList.contains('md:left-4')).toBe(true);
      expect(el.classList.contains('md:bottom-4')).toBe(true);
    });

    it('gives every edition action an icon button with matching tooltip and aria-label', () => {
      const f = render();
      const keys = [
        I18N.gallery.selection.clear, I18N.gallery.selection.select_all, I18N.gallery.selection.invert,
        I18N.gallery.selection.favorite, I18N.gallery.selection.reject, I18N.gallery.selection.rate,
        I18N.albums.add_photos, I18N.gallery.selection.mark_sequence, I18N.gallery.selection.copy_filenames,
        I18N.gallery.selection.edit_tags, I18N.export.action, I18N.cull.action, I18N.cull.delete_action,
        I18N.gallery.selection.download, I18N.gallery.selection.actions,
      ];
      for (const key of keys) {
        const button = labelled(f, key);
        expect(button, key).not.toBeNull();
        expect(button!.classList.contains('mat-mdc-icon-button'), key).toBe(true);
        const tooltip = f.debugElement.queryAll(By.directive(MatTooltip)).find(d => d.nativeElement === button);
        expect(tooltip?.injector.get(MatTooltip).message, key).toBe(key);
      }
    });

    it('shows no text in the buttons other than the icon ligature', () => {
      const f = render();
      for (const button of Array.from(bar(f)!.querySelectorAll('button'))) {
        if (button.closest('.w-full')) continue;
        expect(button.textContent!.trim()).toMatch(/^[a-z_]*$/);
      }
    });

    it('keeps the tooltip on the disabled delete button (disabledInteractive)', () => {
      const f = render({ viewScoped: true });
      const del = labelled(f, I18N.cull.delete_action)!;
      expect(del.getAttribute('aria-disabled')).toBe('true');
      expect(del.disabled).toBe(false);
    });

    // disabledInteractive leaves a <button> clickable, so these must stay natively
    // disabled or a click mid-download starts a second download.
    it('natively disables every download entry point while a download runs', () => {
      for (const profiles of [[], ['web']]) {
        const f = render({ profiles });
        (f.componentInstance as unknown as { downloading: { set(v: boolean): void } }).downloading.set(true);
        f.detectChanges();
        expect(labelled(f, I18N.photo_detail.downloading)!.disabled).toBe(true);
        expect(labelled(f, I18N.gallery.selection.actions)!.disabled).toBe(true);
      }
    });

    it('uses the view-scope text as the delete tooltip when the selection is the whole view', () => {
      const f = render({ viewScoped: true });
      const del = labelled(f, I18N.cull.delete_action)!;
      const tooltip = f.debugElement.queryAll(By.directive(MatTooltip)).find(d => d.nativeElement === del);
      expect(tooltip?.injector.get(MatTooltip).message).toBe(I18N.cull.delete_disabled_view_scope_tooltip);
    });

    it('omits the edit and file actions without edition', () => {
      const f = render({ edition: false });
      expect(labelled(f, I18N.gallery.selection.favorite)).toBeNull();
      expect(labelled(f, I18N.gallery.selection.edit_tags)).toBeNull();
      expect(labelled(f, I18N.cull.delete_action)).toBeNull();
      expect(labelled(f, I18N.gallery.selection.copy_filenames)).not.toBeNull();
    });

    it('hides the desktop group below md and keeps one Actions button', () => {
      const f = render();
      const fav = labelled(f, I18N.gallery.selection.favorite)!;
      expect(fav.closest('.max-md\\:hidden')).not.toBeNull();
      expect(labelled(f, I18N.gallery.selection.actions)!.classList.contains('md:!hidden')).toBe(true);
    });

    it('opens the actions sheet from the Actions button', () => {
      const f = render({ desktop: false });
      const open = vi.spyOn(f.componentInstance as unknown as { openActionsSheet(): Promise<void> }, 'openActionsSheet').mockResolvedValue(undefined);
      labelled(f, I18N.gallery.selection.actions)!.click();
      expect(open).toHaveBeenCalledTimes(1);
    });

    it('calls the same handlers as before for favorite, reject and copy', () => {
      const f = render();
      const inst = f.componentInstance as unknown as { batchFavorite(): void; batchReject(): void; copyPaths(): void };
      const fav = vi.spyOn(inst, 'batchFavorite').mockImplementation(() => undefined);
      const rej = vi.spyOn(inst, 'batchReject').mockImplementation(() => undefined);
      const copy = vi.spyOn(inst, 'copyPaths').mockImplementation(() => undefined);
      labelled(f, I18N.gallery.selection.favorite)!.click();
      labelled(f, I18N.gallery.selection.reject)!.click();
      labelled(f, I18N.gallery.selection.copy_filenames)!.click();
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

    it('dispatches to deleteSelected() when the sheet resolves { kind: "delete" }', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock).mockReturnValue({ afterDismissed: () => of({ kind: 'delete' }) });
      const spy = vi.spyOn(component, 'deleteSelected').mockResolvedValue();

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

      component.openExportDialog();

      expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
    });

    it('sends the filter payload, exclude list and count under view scope, with no paths key', () => {
      mockStore.selectionScope.set('view');
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);

      component.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ filters: { page: '1' }, exclude: ['/skip.jpg'], count: 650 });
      expect(data.paths).toBeUndefined();
    });

    it('sends the selected paths under path scope, with no filters key', () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);

      component.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ paths: ['/a.jpg', '/b.jpg'] });
      expect(data.filters).toBeUndefined();
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
        mockStore.photos.set(['/a.jpg', '/b.jpg'].map(photo));
        mockStore.total.set(650);
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionScope.set('view');
        mockStore.selectionCount.set(650);
        dialog = TestBed.inject(MatDialog);
        snackOpen = TestBed.inject(MatSnackBar).open as Mock;
      });

      const favorite = () =>
        (component as unknown as { batchFavorite: () => Promise<void> }).batchFavorite();

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

      await (component as unknown as { markAsPanorama: (k: string) => Promise<void> })
        .markAsPanorama('panorama');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('undo is only offered when it would restore everything', () => {
    const snap = { is_favorite: false, is_rejected: false, star_rating: null };
    let undoRegister: Mock;
    let snackOpen: Mock;

    beforeEach(() => {
      undoRegister = vi.fn();
      vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(undoRegister);
      snackOpen = TestBed.inject(MatSnackBar).open as Mock;
    });

    const reject = () => (component as unknown as { batchReject: () => Promise<void> }).batchReject();

    it.each(['kept', 'undecided'] as const)('offers Undo for a single %s decision without changing selection', async decision => {
      const snapshot = new Map([['/a.jpg', { ...snap, is_kept: false }]]);
      mockStore.batchReview = vi.fn().mockResolvedValue({ snapshot, targeted: 1, count: 1 });
      mockStore.restoreSnapshot.mockResolvedValue(undefined);
      await (component as unknown as { reviewSingle: (path: string, decision: 'kept' | 'undecided') => Promise<unknown> }).reviewSingle('/a.jpg', decision);
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
      (component as unknown as { markAsPanorama: (k: SequenceKind) => Promise<void> }).markAsPanorama(kind);

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
      (component as unknown as { downloadSelected: () => Promise<void> }).downloadSelected();

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

    const copy = () => (component as unknown as { copyPaths: () => Promise<void> }).copyPaths();
    const download = () =>
      (component as unknown as { downloadSelected: () => Promise<void> }).downloadSelected();
    const addToAlbum = () => component.addToAlbum(3);

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
      (component as unknown as { copyPaths: (p?: string[]) => Promise<void> }).copyPaths(paths);
    const download = (paths?: string[]) =>
      (component as unknown as { downloadSelected: (t?: string, pr?: string, p?: string[]) => Promise<void> })
        .downloadSelected('original', undefined, paths);

    it('addToAlbum adds exactly the given paths and leaves the selection alone', async () => {
      await component.addToAlbum(3, ['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect(mockStore.pathsInView).not.toHaveBeenCalled();
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('an empty paths list is a no-op, never a fall-back to the selection', async () => {
      await component.addToAlbum(3, []);
      await copy([]);

      expect(addPhotos).not.toHaveBeenCalled();
      expect(writeText).not.toHaveBeenCalled();
    });

    it('addToAlbum without paths still adds the selection and clears it', async () => {
      await component.addToAlbum(3);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/a.jpg', '/b.jpg', '/c.jpg']);
      expect(mockStore.clearSelection).toHaveBeenCalled();
    });

    it('createAlbumAndAdd forwards the paths to addToAlbum', async () => {
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of({ id: 9, name: 'N' }) });

      await component.createAlbumAndAdd(['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(9, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    describe('under a whole-view selection', () => {
      beforeEach(() => {
        selectView();
        mockStore.pathsInView.mockResolvedValue(['/q.jpg']);
      });

      it('addToAlbum, copyPaths and downloadSelected use the given paths without asking the server', async () => {
        await component.addToAlbum(3, ['/x.jpg']);
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

        component.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });

      it('still exports the whole album on an album route when no paths are given', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');

        component.openExportDialog();

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
      });

      it('ignores view scope when paths are given', () => {
        selectView();

        component.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });
    });

    describe('openCullDialog', () => {
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

        await component.openCullDialog(['/x.jpg']);

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

        await component.openCullDialog(['/x.jpg']);

        expect(mockStore.viewScopeSelected()).toBe(true);
        expect(mockStore.selectionScope()).toBe('view');
        expect([...mockStore.excludedPaths()].sort()).toEqual(['/e.jpg', '/x.jpg']);
      });

      it('drops the target from a path selection, and only it', async () => {
        mockStore.selectedPaths.set(new Set(['/a.jpg', '/x.jpg']));
        mockStore.selectionCount.set(2);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()]).toEqual(['/a.jpg']);
        expect(mockStore.selectionScope()).toBe('paths');
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('leaves a path selection alone when the target was not selected', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('touches nothing when the dialog is dismissed', async () => {
        mockStore.selectedPaths.set(new Set(['/x.jpg']));
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.openCullDialog(['/x.jpg']);

        expect(mockStore.loadPhotos).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
      });
    });

    describe('deleteSelected', () => {
      const confirmed = { includeCompanions: false, includeSequenceSiblings: false };
      const deleted = (paths: string[]) => of({
        dry_run: false, deleted: paths, not_found: [], not_visible: [], refused_bracket_lead: [],
        sequence_siblings: [], skipped: [], trashed: paths.length, errors: {},
      });

      it('opens the single-photo dialog under view scope, where the no-arg form refuses', async () => {
        selectView();
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.deleteSelected(['/x.jpg']);

        const data = (dialog.open as Mock).mock.calls[0][1].data;
        expect(data.surface).toBe('photo_detail');
        expect(data.paths).toEqual(['/x.jpg']);
        expect(data.count).toBe(1);
      });

      it('removes only the deleted path and does not clear the selection', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(confirmed) });
        mockApi.post.mockReturnValueOnce(deleted(['/x.jpg']));

        await component.deleteSelected(['/x.jpg']);

        expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', expect.objectContaining({ paths: ['/x.jpg'] }));
        expect(mockStore.removePhotos).toHaveBeenCalledWith(['/x.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('returns without a dialog when the photo is no longer loaded', async () => {
        await component.deleteSelected(['/gone.jpg']);

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
          await component.deleteSelected([path]);
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

        await component.deleteSelected();

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
      vi.spyOn(component as unknown as Record<string, (...a: unknown[]) => unknown>, name)
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
      vi.spyOn(fixture!.componentInstance as unknown as Record<string, (...a: unknown[]) => unknown>, 'openExportDialog')
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

    afterEach(() => fixture.destroy());

    function openPhoto(index: number): HTMLElement {
      const tile = fixture.nativeElement.querySelector(`[data-pidx="${index}"] [tabindex]`) as HTMLElement;
      tile.focus();
      // Real navigation needs routes this spec does not have; the gallery only listens for the start.
      (TestBed.inject(Router).events as Subject<RouterEvent>).next(new NavigationStart(1, `/photo?path=${photos[index].path}`));
      outletMock.detachEvents.next(gallery);
      tile.blur();
      return tile;
    }

    it('defers the filter sidebar until its block is rendered', async () => {
      expect(fixture.debugElement.query(By.directive(GalleryFilterSidebarComponent))).toBeNull();
      const blocks = await fixture.getDeferBlocks();
      expect(blocks).toHaveLength(1);
      await blocks[0].render(DeferBlockState.Complete);
      expect(fixture.debugElement.query(By.directive(GalleryFilterSidebarComponent))).not.toBeNull();
    });

    it('cancels pending sidebar searches when the gallery is parked', async () => {
      mockStore.config.set({ features: { show_semantic_search: true } });
      const [sidebarBlock] = await fixture.getDeferBlocks();
      await sidebarBlock.render(DeferBlockState.Complete);
      const sidebar = fixture.debugElement.query(By.directive(GalleryFilterSidebarComponent)).componentInstance as GalleryFilterSidebarComponent;
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
      expect(TestBed.inject(HeaderSlotService).template()).toBeNull();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
      expect(mockStore.loadFilterOptions).not.toHaveBeenCalled();
      outletMock.attachEvents.next(gallery);
      expect(TestBed.inject(HeaderSlotService).template()).not.toBeNull();
      expect(mockStore.loadTypeCounts).toHaveBeenCalledOnce();
      expect(mockStore.loadFilterOptions).toHaveBeenCalledOnce();
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

    it('hands the header toolbar back while a photo is open, and takes it again on return', () => {
      const header = TestBed.inject(HeaderSlotService);
      expect(header.template()).not.toBeNull();
      openPhoto(1);
      expect(header.template()).toBeNull();
      outletMock.attachEvents.next(gallery);
      expect(header.template()).not.toBeNull();
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
        const sidebar = fixture.debugElement.query(By.directive(GalleryFilterSidebarComponent));
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
      const header = TestBed.inject(HeaderSlotService);
      outletMock.detachEvents.next({});
      expect(header.template()).not.toBeNull();
    });
  });
});
