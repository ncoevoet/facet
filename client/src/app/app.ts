import { pathOf } from './shared/utils/url-path';
import { Component, inject, computed, signal, effect, untracked, OnInit, ChangeDetectionStrategy, DestroyRef, ElementRef, viewChild, afterRenderEffect } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterOutlet, RouterLink, NavigationEnd } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map, firstValueFrom } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { SwUpdate, VersionReadyEvent } from '@angular/service-worker';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatInputModule } from '@angular/material/input';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { FEATURE_MARK, MarkTonePipe } from './shared/pipes/mark-tone.pipe';
import { ApiService } from './core/services/api.service';
import { StalenessGuardFactory } from './core/services/staleness-guard.service';
import { AuthService } from './core/services/auth.service';
import { ScanService } from './core/services/scan.service';
import { I18nService } from './core/services/i18n.service';
import { ThemeService } from './core/services/theme.service';
import { PageHelpService } from './core/services/page-help.service';
import { HeaderSlotService } from './core/services/header-slot.service';
import { GeoPhotosService } from './core/services/geo-photos.service';
import { GalleryStore } from './features/gallery/gallery.store';
import { AlbumsFiltersService } from './features/albums/albums-filters.service';
import { PersonsFiltersService } from './features/persons/persons-filters.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { CapsuleFiltersService } from './features/capsules/capsule-filters.service';
import { TranslatePipe } from './shared/pipes/translate.pipe';
import { copyText } from './shared/utils/clipboard';
import { AlbumTypeIconPipe } from './features/albums/album-type-icon.pipe';
import { HelpDialogComponent } from './shared/components/help-dialog/help-dialog.component';
import { CULLING_SHORTCUT_SECTIONS, STACK_SHORTCUT_SECTIONS, MANUAL_STACK_SHORTCUT_SECTIONS } from './features/gallery/culling-shortcuts';
import { galleryShortcutSection, ShortcutSection } from './features/gallery/gallery-shortcuts';
import { KeyboardMappingDialogComponent } from './shared/components/keyboard-mapping-dialog/keyboard-mapping-dialog.component';
import { KeyboardMappingService } from './core/services/keyboard-mapping.service';
import { AssistantActivityChipComponent } from './features/agent/assistant-activity-chip.component';
import { CONNECT_ASSISTANT_DIALOG_ID } from './core/agent/page-context.service';
import { SlideshowComponent } from './features/gallery/slideshow.component';
import { Photo, normalisePhotoFlagsAll } from './shared/models/photo.model';
import { DateRangeFilterComponent } from './shared/components/date-range-filter/date-range-filter.component';
import { I18N, i18nKeys } from './core/i18n/keys';
import { I18nTitleStrategy } from './core/i18n-title.strategy';
import { MOBILE_BAR_BUTTON, MOBILE_BAR_ROW } from './shared/utils/mobile-bar';

/** When the "a newer Facet is out" notice was last shown, so it stays weekly. */
const RELEASE_NOTICE_KEY = 'facet_release_notice_shown';
const RELEASE_NOTICE_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;

/** Response of GET /api/updates/check. */
interface ReleaseCheck {
  enabled: boolean;
  current: string;
  latest: string | null;
  update_available: boolean;
  release_url: string;
}

/** Inline dialog for edition password prompt. */
@Component({
  selector: 'app-edition-dialog',
  imports: [FormsModule, MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule, MatDialogModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="flex items-center gap-2 truncate">
      <mat-icon>lock_open</mat-icon>
      {{ I18N.edition.unlock_title | translate }}
    </h2>
    <mat-dialog-content>
      <p class="text-sm text-[var(--mat-sys-on-surface-variant)] mb-3">{{ I18N.edition.unlock_description | translate }}</p>
      <mat-form-field class="w-full">
        <mat-label>{{ I18N.edition.password_placeholder | translate }}</mat-label>
        <input matInput type="password" [(ngModel)]="password" (keyup.enter)="submit()" />
      </mat-form-field>
      @if (error()) {
        <p class="text-red-400 text-sm">{{ error()! | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.dialog.cancel | translate }}</button>
      <button mat-flat-button [disabled]="!password" (click)="submit()">{{ I18N.edition.unlock_button | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class EditionDialogComponent {
  protected readonly I18N = i18nKeys();
  private dialogRef = inject(MatDialogRef<EditionDialogComponent>);
  private auth = inject(AuthService);
  protected password = '';
  /** The translation key to show, or null while there is nothing to report.
   *  A key rather than a boolean because the failures differ: a wrong
   *  password, a server that could not read its own config and is refusing
   *  to authenticate anyone, and a rate limit rejected before any password
   *  check ran. */
  protected readonly error = signal<string | null>(null);

  async submit(): Promise<void> {
    this.error.set(null);
    const outcome = await this.auth.editionLogin(this.password);
    if (outcome === 'ok') {
      this.dialogRef.close(true);
      return;
    }
    this.error.set(
      outcome === 'unavailable' ? I18N.auth.config_unreadable
        : outcome === 'rate_limited' ? I18N.errors.rate_limited
          : I18N.edition.invalid_password,
    );
  }
}

@Component({
  selector: 'app-root',
  imports: [
    AssistantActivityChipComponent,
    RouterOutlet,
    RouterLink,
    MatToolbarModule,
    MatSidenavModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatSelectModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatInputModule,
    MatDividerModule,
    TranslatePipe,
    MarkTonePipe,
    AlbumTypeIconPipe,
    NgTemplateOutlet,
    DateRangeFilterComponent,
    SlideshowComponent,
  ],
  templateUrl: './app.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  host: {
    class: 'block h-full',
    '(document:keydown)': 'onGlobalKeydown($event)',
  },
})
export class App implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly featureMark = FEATURE_MARK;
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);
  private readonly staleness = inject(StalenessGuardFactory);
  protected readonly scan = inject(ScanService);
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly geoPhotos = inject(GeoPhotosService);
  protected readonly i18n = inject(I18nService);
  protected readonly themeService = inject(ThemeService);
  protected readonly pageHelp = inject(PageHelpService);
  private readonly keymap = inject(KeyboardMappingService);

  /** Read-only Immich status for whoever may administer the installation. */
  protected async openImmichDiagnostics(): Promise<void> {
    const { current, dispose } = this.staleness.create(this.destroyRef, {
      valid: () => this.auth.isInstallAdmin(),
    });
    try {
      const { ImmichDiagnosticsDialogComponent } = await import('./features/immich/immich-diagnostics-dialog.component');
      if (current()) this.dialog.open(ImmichDiagnosticsDialogComponent, { width: '34rem', autoFocus: false });
    } finally { dispose(); }
  }

  /** The keyboard settings dialog: reassign the primary key of the gallery
   *  and photo-page actions. Reachable from every route, like Help. */
  protected openKeymapDialog(): void {
    this.dialog.open(KeyboardMappingDialogComponent, { width: '26rem', autoFocus: false });
  }

  /** The menu's Help entry opens a modal with the current page's help text
   *  and, on the gallery and culling routes, that page's keyboard reference.
   *  The sections resolve from the router URL at click time; the dialog must
   *  not read router state itself, because its construction timing is not
   *  guaranteed to see the active route. */
  protected openHelpDialog(): void {
    const shortcuts = this.helpSections();
    this.dialog.open(HelpDialogComponent, {
      width: '32rem', autoFocus: false,
      data: { key: this.pageHelp.descriptionKey(), note: this.pageHelp.note(), shortcutSections: shortcuts },
    });
  }
  /** Copy "Facet <version> (<build>)" from the user menu; the build is left out when the server sends none. */
  protected async copyVersion(): Promise<void> {
    const config = this.store.config();
    if (!config?.version) return;
    const label = this.i18n.t(I18N.ui.version, { version: config.version });
    const text = config.build ? `${label} (${config.build})` : label;
    if (await copyText(text)) {
      this.snackBar.open(this.i18n.t(I18N.notifications.copied), '', { duration: 2000 });
    } else {
      this.snackBar.open(this.i18n.t(I18N.ui.copy_failed), '', { duration: 3000 });
    }
  }
  private helpSections(): ShortcutSection[] {
    const url = this.url();
    const path = url.split(/[?#]/)[0];
    if (path.startsWith('/culling')) {
      return this.router.parseUrl(url).queryParams['mode'] === 'stacks' ? STACK_SHORTCUT_SECTIONS : CULLING_SHORTCUT_SECTIONS;
    }
    if (path === '/stacks/edit') return MANUAL_STACK_SHORTCUT_SECTIONS;
    return this.isGalleryRoute() ? [galleryShortcutSection(this.keymap.keymap())] : [];
  }
  protected readonly headerSlot = inject(HeaderSlotService);
  protected readonly store = inject(GalleryStore);
  protected readonly albumsFilters = inject(AlbumsFiltersService);
  protected readonly personsFilters = inject(PersonsFiltersService);
  protected readonly compareFilters = inject(CompareFiltersService);
  protected readonly capsuleFilters = inject(CapsuleFiltersService);
  protected readonly navigationDestinations = computed(() => {
    const features = this.store.config()?.features;
    const path = pathOf(this.url());
    const tools = new Set(['/culling', '/scenes', '/junk', '/stats', '/compare']);
    return [
      { path: '/', icon: 'diamond', label: I18N.nav.gallery, tooltipKey: I18N.nav.gallery_tooltip, visible: true },
      { path: '/albums', icon: 'photo_album', label: I18N.nav.albums, tooltipKey: I18N.nav.tooltips.albums, visible: features?.show_albums },
      { path: '/capsules', icon: 'auto_stories', label: I18N.nav.capsules, tooltipKey: I18N.nav.tooltips.capsules, visible: features?.show_capsules },
      { path: '/timeline', icon: 'view_timeline', label: I18N.nav.timeline, tooltipKey: I18N.nav.tooltips.timeline, visible: features?.show_timeline },
      { path: '/folders', icon: 'folder', label: I18N.nav.folders, tooltipKey: I18N.nav.tooltips.folders, visible: features?.show_folders },
      { path: '/persons', icon: 'people', label: I18N.nav.persons, tooltipKey: I18N.nav.tooltips.persons, visible: true },
      { path: '/map', icon: 'map', label: I18N.nav.map, tooltipKey: I18N.nav.tooltips.map, visible: features?.show_map && this.geoPhotos.available() },
      { path: '/culling', icon: 'burst_mode', label: I18N.nav.culling, tooltipKey: I18N.nav.tooltips.culling, visible: this.auth.isEdition() },
      { path: '/scenes', icon: 'movie_filter', label: I18N.nav.scenes, tooltipKey: I18N.nav.tooltips.scenes, visible: features?.show_scenes },
      { path: '/junk', icon: 'delete_sweep', label: I18N.nav.junk_sweep, tooltipKey: I18N.nav.tooltips.junk_sweep, visible: this.auth.isEdition() && features?.show_junk_sweep },
      { path: '/stats', icon: 'bar_chart', label: I18N.nav.stats, tooltipKey: I18N.nav.tooltips.stats, visible: true },
      { path: '/compare', icon: 'compare', label: I18N.nav.compare, tooltipKey: I18N.nav.tooltips.compare, visible: this.auth.isEdition() },
    ].filter(item => item.visible).map((item, index, items) => ({ ...item,
      tool: tools.has(item.path),
      groupStart: index > 0 && tools.has(item.path) && !tools.has(items[index - 1].path),
      active: item.path === '/' ? this.isGalleryRoute() && !path.startsWith('/album/')
        : path === item.path || path.startsWith(item.path + '/') || (item.path === '/albums' && path.startsWith('/album/')),
    }));
  });
  private readonly navigationSpace = viewChild<ElementRef<HTMLElement>>('navigationSpace');
  private readonly navigationMeasurements = viewChild<ElementRef<HTMLElement>>('navigationMeasurements');
  protected readonly desktopTabCount = signal(Number.MAX_SAFE_INTEGER);
  private readonly titleStrategy = inject(I18nTitleStrategy);
  protected readonly MOBILE_BAR_ROW = MOBILE_BAR_ROW;
  protected readonly MOBILE_BAR_BUTTON = MOBILE_BAR_BUTTON;
  /** The phone header's title key: the current destination's label, else the route's own title, else none (the brand text shows). */
  protected readonly phoneTitleKey = computed(() => this.navigationDestinations().find(destination => destination.active)?.label ?? this.titleStrategy.titleKey() ?? null);
  protected readonly desktopDestinations = computed(() => this.navigationDestinations().slice(0, this.desktopTabCount()));
  protected readonly overflowDestinations = computed(() => this.navigationDestinations().slice(this.desktopTabCount()));
  protected readonly memoriesNavigationAvailable = computed(() => !!this.store.config()?.features?.show_memories && this.hasMemories());
  protected readonly memoriesInTabs = computed(() => this.memoriesNavigationAvailable() && this.desktopTabCount() > this.navigationDestinations().length);
  protected readonly showMoreDestinations = computed(() => this.overflowDestinations().length > 0 || (this.memoriesNavigationAvailable() && !this.memoriesInTabs()));
  protected readonly overflowDestinationActive = computed(() => this.overflowDestinations().some(item => item.active));

  protected readonly mobileAlbumsSearchOpen = signal(false);
  private readonly mobileAlbumsSearchInput = viewChild<ElementRef<HTMLInputElement>>('mobileAlbumsSearchInput');
  private readonly mobileAlbumsSearchTrigger = viewChild('mobileAlbumsSearchTrigger', { read: ElementRef<HTMLButtonElement> });
  private readonly restoreAlbumsSearchFocus = signal(false);

  protected onMobileAlbumsSearchEscape(event: Event): void {
    if (!this.mobileAlbumsSearchOpen()) return;
    event.preventDefault();
    event.stopPropagation();
    this.closeMobileAlbumsSearch(false);
  }

  protected closeMobileAlbumsSearch(clear = true): void {
    if (clear) this.albumsFilters.search.set('');
    this.mobileAlbumsSearchOpen.set(false);
    this.restoreAlbumsSearchFocus.set(true);
  }
  protected readonly mobilePersonsSearchOpen = signal(false);
  protected readonly hasMemories = signal(false);

  // "On This Day" diaporama (fullscreen slideshow over the shell).
  protected readonly memoriesActive = signal(false);
  protected readonly memoriesPhotos = signal<Photo[]>([]);
  protected readonly memoriesLoading = signal(false);
  // Personal ranker ("My Taste") training status — powers the confidence badge
  // shown when sorting by learned_score. null until fetched / when unavailable.
  protected readonly rankerStatus = signal<{
    trained: boolean; comparison_count: number; coverage: number; cv_accuracy: number | null;
    baseline_accuracy: number | null;
  } | null>(null);
  // Badge view-model: only when the "My Taste" sort is active and the ranker has
  // trained (else null -> no badge).
  protected readonly myTasteBadge = computed(() => {
    const s = this.rankerStatus();
    if (this.store.filters().sort !== 'learned_score' || !s?.trained) return null;
    return {
      accuracy: s.cv_accuracy != null ? Math.round(s.cv_accuracy) : null,
      baseline: s.baseline_accuracy != null ? Math.round(s.baseline_accuracy) : null,
      comparisons: s.comparison_count ?? 0,
    };
  });

  private url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map(e => e.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  protected readonly isGalleryRoute = computed(() => {
    const path = this.url().split('?')[0];
    return path === '/' || path === '' || path.startsWith('/album/');
  });

  protected readonly isCompareRoute = computed(() => this.url().split('?')[0] === '/compare');
  protected readonly isAlbumsRoute = computed(() => this.url().split('?')[0] === '/albums');
  protected readonly isPersonsRoute = computed(() => this.url().split('?')[0] === '/persons');
  protected readonly isCapsuleRoute = computed(() => this.url().split('?')[0] === '/capsules');
  protected readonly isTimelineRoute = computed(() => this.url().split('?')[0].startsWith('/timeline'));
  protected readonly isSharedRoute = computed(() => this.url().split('?')[0].startsWith('/shared/'));

  /** A route gets a second bar only when it actually supplies page controls. */
  protected readonly showPageToolbar = computed(() => !this.auth.isAuthenticated()
    || this.isCompareRoute() || this.headerSlot.template() !== null);

  protected readonly mobilePersonsBarVisible = computed(() => this.isPersonsRoute() && !this.personsFilters.selectedIds().size);


  /** Open the keyboard shortcuts reference with '?' unless typing in a field. */
  protected onGlobalKeydown(event: KeyboardEvent): void {
    if (event.key !== '?') return;
    const target = event.target as HTMLElement | null;
    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
    if (target?.isContentEditable) return;
    if (document.querySelector('mat-dialog-container')) return;
    event.preventDefault();
    this.openShortcutsDialog();
  }

  protected openShortcutsDialog(): void {
    import('./shared/components/shortcuts-dialog/shortcuts-dialog.component').then(m => {
      this.dialog.open(m.ShortcutsDialogComponent, { autoFocus: false });
    });
  }

  private readonly snackBar = inject(MatSnackBar);
  private readonly swUpdate = inject(SwUpdate, { optional: true });

  /** Offer a reload when the service worker has installed a new version. */
  private setupUpdateNotifications(): void {
    if (!this.swUpdate?.isEnabled) return;
    this.swUpdate.versionUpdates
      .pipe(filter((e): e is VersionReadyEvent => e.type === 'VERSION_READY'))
      .subscribe(() => {
        const ref = this.snackBar.open(
          this.i18n.t(I18N.pwa.update_available), this.i18n.t(I18N.pwa.reload),
        );
        ref.onAction().subscribe(() => location.reload());
      });
  }

  /**
   * Mention once a week that a newer Facet has been released.
   *
   * Separate from the service worker's notice above, which reloads the page onto
   * a bundle already downloaded; this one is about a release nobody has installed
   * yet. Only edition users see it — upgrading is an operator's job, and telling
   * anyone else would be nagging them about something they cannot act on.
   *
   * The weekly stamp is written as soon as the notice is shown, not when it is
   * dismissed, so a reload cannot turn it into a notice on every page load.
   */
  private async maybeAnnounceNewRelease(): Promise<void> {
    if (!this.auth.isEdition()) return;
    const now = Date.now();
    const last = Number(localStorage.getItem(RELEASE_NOTICE_KEY)) || 0;
    if (now - last < RELEASE_NOTICE_INTERVAL_MS) return;
    try {
      const res = await firstValueFrom(this.api.get<ReleaseCheck>('/updates/check'));
      if (!res?.update_available || !res.latest) return;
      localStorage.setItem(RELEASE_NOTICE_KEY, String(now));
      const ref = this.snackBar.open(
        this.i18n.t(I18N.updates.available, { version: res.latest }),
        res.release_url ? this.i18n.t(I18N.updates.view) : '',
        { duration: 15000 },
      );
      if (res.release_url) {
        ref.onAction().subscribe(() => window.open(res.release_url, '_blank', 'noopener'));
      }
    } catch {
      // A check that cannot run is not worth a word to the user.
    }
  }

  /** Auth identity fingerprint, to refresh config only on real transitions. */
  private lastAuthKey: string | null = null;

  constructor() {
    afterRenderEffect(() => {
      if (this.mobileAlbumsSearchOpen()) this.mobileAlbumsSearchInput()?.nativeElement.focus();
      else if (this.restoreAlbumsSearchFocus()) {
        this.mobileAlbumsSearchTrigger()?.nativeElement.focus();
        this.restoreAlbumsSearchFocus.set(false);
      }
    });
    afterRenderEffect(cleanup => {
      const space = this.navigationSpace()?.nativeElement;
      const measurements = this.navigationMeasurements()?.nativeElement;
      if (!space || !measurements) return;
      const fit = () => {
        const available = space.getBoundingClientRect().width;
        if (!available) return; // The mobile shell has its own navigation menu.
        const widths = Array.from(measurements.querySelectorAll<HTMLElement>('[data-navigation-measure]'))
          .map(item => item.getBoundingClientRect().width);
        let count = widths.length;
        if (widths.reduce((sum, width) => sum + width, 0) > available) {
          let used = measurements.querySelector<HTMLElement>('[data-more-measure]')!.getBoundingClientRect().width + 4;
          count = 0;
          for (const width of widths) {
            if (used + width > available) break;
            used += width;
            count++;
          }
        }
        this.desktopTabCount.set(count);
      };
      const resize = new ResizeObserver(fit);
      resize.observe(space);
      resize.observe(measurements);
      // Labels and feature/access changes can alter the prefix widths even
      // when their combined width happens to stay the same.
      const content = new MutationObserver(fit);
      content.observe(measurements, { childList: true, characterData: true, subtree: true });
      fit();
      cleanup(() => { resize.disconnect(); content.disconnect(); });
    });
    // When the signed-in identity or its rights change (login, edition grant or
    // drop), re-fetch the viewer config so config-derived nav/features reflect the
    // new rights immediately — refreshConfig() leaves the user's filters intact.
    effect(() => {
      const s = this.auth.status();
      // A rotated token clears status while its new account is being checked.
      // Keep the last known identity until that check settles, so the pending
      // state cannot swallow the config refresh for the actual transition.
      if (!s) return;
      const key = `${s.authenticated}|${s.user_id ?? ''}|${s.edition_authenticated}|${s.user_role ?? ''}`;
      untracked(() => {
        if (this.lastAuthKey !== null && key !== this.lastAuthKey) {
          void this.store.refreshConfig();
          // Edition-only indicators loaded once at startup must refresh when
          // edition is gained mid-session (otherwise they'd need an app reload).
          if (s?.edition_authenticated) {
            void this.maybeAnnounceNewRelease();
          }
        }
        this.lastAuthKey = key;
      });
    });
  }

  async ngOnInit(): Promise<void> {
    this.setupUpdateNotifications();
    await this.i18n.loadLanguages();
    await this.i18n.load();
    this.store.loadTypeCounts();
    void this.store.loadConfig(() => this.store.galleryMounts() === 0);
    try {
      await this.auth.checkStatus();
      const promises: Promise<void>[] = [];
      if (this.auth.isEdition()) {
        // A page load that starts already in edition mode is not a transition,
        // so the effect below never sees it (lastAuthKey's own first resolution
        // is exempt, same as the config-refresh it guards); a later mid-session
        // grant is still caught there, with the weekly stamp stopping a re-notify.
        void this.maybeAnnounceNewRelease();
      }
      // "My Taste" confidence badge: the personal-ranker training status. Fetched
      // for everyone (the global pooled ranker is a shared sort, not edition-only).
      promises.push(
        firstValueFrom(
          this.api.get<{ trained: boolean; comparison_count: number; coverage: number; cv_accuracy: number | null; baseline_accuracy: number | null }>('/ranker/status'),
        ).then(data => {
          this.rankerStatus.set(data);
        }).catch(() => { /* Non-critical */ }),
      );
      promises.push(
        firstValueFrom(
          this.api.get<{ has_memories: boolean }>('/memories/check'),
        ).then(data => {
          this.hasMemories.set(data.has_memories);
        }).catch(() => { /* Non-critical */ }),
      );
      promises.push(this.geoPhotos.refresh());
      await Promise.all(promises);
    } catch {
      // Auth check failed — guard will redirect if needed
    }
  }


  protected onCompareCategoryChange(cat: string): void {
    this.compareFilters.selectedCategory.set(cat);
  }

  protected switchLang(lang: string): void {
    this.i18n.setLocale(lang);
  }

  protected logout(): void {
    this.auth.logout();
  }

  protected async openScanLauncher(): Promise<void> {
    if (await this.scan.openLauncher()) {
      await this.store.loadTypeCounts();
      await this.store.reloadPhotos();
    }
  }

  protected async showConnectAssistantDialog(): Promise<void> {
    const { ConnectAssistantDialogComponent } = await import('./features/agent/connect-assistant-dialog.component');
    this.dialog.open(ConnectAssistantDialogComponent, { id: CONNECT_ASSISTANT_DIALOG_ID, width: '95vw', maxWidth: '640px' });
  }

  protected showEditionDialog(): void {
    this.dialog.open(EditionDialogComponent, { width: '95vw', maxWidth: '360px' });
  }

  protected async lockEdition(): Promise<void> {
    if (!await this.auth.dropEdition()) {
      this.snackBar.open(this.i18n.t(I18N.edition.lock_failed), '', { duration: 5000 });
      return;
    }
    const path = this.url().split('?')[0];
    const onEditionRoute = this.router.config.some(r => {
      const base = `/${r.path}`;
      return r.data?.['edition'] === true && (path === base || path.startsWith(`${base}/`));
    });
    if (onEditionRoute) {
      this.router.navigate(['/']);
    }
  }

  protected loadOrganizationHistoryDialog() { return import('./features/photo-detail/organization-history-dialog.component'); }

  protected loadProcessingDialog() { return import('./features/gallery/export-editor-dialog.component'); }

  async openProcessing(): Promise<void> {
    if (!this.auth.isEdition()) return;
    const liveness = this.staleness.create(this.destroyRef);
    try {
      const { ExportEditorDialogComponent } = await this.loadProcessingDialog();
      if (!liveness.current()) return;
      this.dialog.open(ExportEditorDialogComponent, {
        width: '95vw', maxWidth: '780px', data: { receiptsOnly: true },
      });
    } finally { liveness.dispose(); }
  }

  /** The account's latest organization changes across the library, from any page. */
  async openOrganizationHistory(): Promise<void> {
    if (!this.auth.isEdition()) return;
    const liveness = this.staleness.create(this.destroyRef);
    try {
      const { OrganizationHistoryDialogComponent } = await this.loadOrganizationHistoryDialog();
      if (!liveness.current()) return;
      const ref = this.dialog.open(OrganizationHistoryDialogComponent, { width: '95vw', maxWidth: '820px' });
      const history = ref.componentInstance;
      // A restore may rewrite the photo an open detail page holds its own copy of.
      void firstValueFrom(ref.afterClosed()).then(() => history.whenSettled()).then(() => {
        if (history.wasRestored()) this.store.notifyOrganizationRestored();
      });
    } finally { liveness.dispose(); }
  }

  /** "On This Day" diaporama: fetch this date's photos from past years, shuffle
   *  them, and play them as a fullscreen slideshow (replaces the old grid modal). */
  protected async playMemories(): Promise<void> {
    if (this.memoriesActive()) return;
    this.memoriesLoading.set(true);
    this.memoriesActive.set(true);
    this.memoriesPhotos.set([]);
    try {
      const res = await firstValueFrom(
        this.api.get<{ years: { photos: Photo[] }[] }>('/memories'),
      );
      const photos = normalisePhotoFlagsAll((res.years ?? []).flatMap(y => y.photos ?? []));
      if (photos.length === 0) {
        this.memoriesActive.set(false);
        this.snackBar.open(this.i18n.t(I18N.memories.no_memories), '', { duration: 3000 });
        return;
      }
      for (let i = photos.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [photos[i], photos[j]] = [photos[j], photos[i]];
      }
      this.memoriesPhotos.set(photos);
    } catch {
      this.memoriesActive.set(false);
    } finally {
      this.memoriesLoading.set(false);
    }
  }

  protected closeMemories(): void {
    this.memoriesActive.set(false);
    this.memoriesPhotos.set([]);
  }

  protected onPersonsSortChange(sort: string): void {
    this.personsFilters.sort.set(sort);
  }

  protected togglePersonsSortDirection(): void {
    this.personsFilters.sortDirection.update(d => d === 'desc' ? 'asc' : 'desc');
  }

  protected resetAllFilters(): void {
    this.router.navigate(['/']);
    this.store.resetFilters();
  }
}
