import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { computed, signal, WritableSignal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { buildApiParams, DISPLAY_OPTIONS_KEY } from './gallery-filters.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { GalleryComponent } from './gallery.component';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';
import { MAX_COMPARE_PANES } from './synced-zoom.component';
import { gridColumnCount } from './gallery-rows.util';
import { UndoService } from '../../core/services/undo.service';

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

  beforeEach(() => {
    mockStore = {
      filters: signal<GalleryFilters>({ ...DEFAULT_FILTERS }),
      types: signal([
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 200 },
        { id: 'macro', label: 'Macro', count: 50 },
      ]),
      photos: signal([]),
      total: signal(0),
      loading: signal(false),
      loadError: signal(false),
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
      galleryMode: signal('mosaic'),
      cardWidth: signal(300),
      virtualScroll: signal(false),
      setFilterDrawerOpen: vi.fn(),
      loadConfig: vi.fn(() => Promise.resolve()),
      loadFilterOptions: vi.fn(() => Promise.resolve()),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
      loadPhotos: vi.fn(() => Promise.resolve()),
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
      filterKey: vi.fn((f?: GalleryFilters) => JSON.stringify(buildApiParams(f ?? mockStore.filters(), false))),
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

    mockAuth = { isEdition: vi.fn(() => false) };

    mockI18n = {
      t: vi.fn((key: string) => key),
      translations: signal<Record<string, unknown>>({}),
      lang: signal('en'),
    };

    routeMock = { snapshot: { paramMap: { get: vi.fn(() => null) }, queryParams: {} } };

    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
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
        { provide: MatDialog, useValue: { open: vi.fn() } },
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
    });
    component = TestBed.runInInjectionContext(() => new GalleryComponent());
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
      mockStore.loadPhotos.mockImplementation(() => {
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

    const mark = (kind: 'panorama' | 'hdr_panorama' = 'panorama') =>
      (component as unknown as { markAsPanorama: (k: string) => Promise<void> }).markAsPanorama(kind);

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
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
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
});
