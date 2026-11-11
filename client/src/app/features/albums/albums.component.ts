import { Component, inject, signal, computed, effect, untracked, viewChild, TemplateRef, DestroyRef, ChangeDetectionStrategy, afterNextRender, Injector } from '@angular/core';
import { HttpContext } from '@angular/common/http';
import { DOCUMENT } from '@angular/common';
import { RouterLink, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { LatestRequest } from '../../shared/utils/latest-request';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ThumbnailSrcsetPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { EditAlbumDialogComponent } from './edit-album-dialog.component';
import { ClientPicksDialogComponent, ClientPicksDialogData } from './client-picks-dialog.component';
import { PortfolioExportDialogComponent, PortfolioExportDialogData } from './portfolio-export-dialog.component';
import { AlbumScoringContextDialogComponent, AlbumScoringContextDialogData } from './album-scoring-context-dialog.component';
import { AlbumsFiltersService, AlbumTypeFilter } from './albums-filters.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { ShareDialogComponent, ShareDialogData } from '../../shared/components/share-dialog/share-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { onPageQuery } from '../../shared/utils/page-query';
import { AlbumTypeIconPipe } from './album-type-icon.pipe';
import { MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { AlbumDialogContext } from './album-dialog-context';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { SelectTriggerLabelComponent } from '../../shared/components/select-trigger-label/select-trigger-label.component';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block px-4 pt-4 pb-4' },
  imports: [
    SelectTriggerLabelComponent,
    RouterLink, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule,
    MatSelectModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule, MatMenuModule, MarkTonePipe, AlbumTypeIconPipe,
    TranslatePipe, ThumbnailUrlPipe, ThumbnailSrcsetPipe, InfiniteScrollDirective,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <ng-template #albumsToolbar>
      <mat-form-field class="!hidden lg:!inline-flex w-52" subscriptSizing="dynamic">
        <mat-label>{{ 'albums.search' | translate }}</mat-label>
        <input matInput [value]="albumsFilters.search()" (input)="albumsFilters.search.set($any($event.target).value)" />
        <mat-icon matPrefix class="opacity-60">search</mat-icon>
      </mat-form-field>
      <mat-form-field class="!hidden lg:!inline-flex w-36" subscriptSizing="dynamic">
        <mat-label>{{ 'albums.filter_type' | translate }}</mat-label>
        <mat-select [value]="albumsFilters.typeFilter()" (selectionChange)="albumsFilters.typeFilter.set($event.value)">
          <mat-select-trigger>
            @let currentType = albumsFilters.typeFilter() | albumTypeIcon;
            <app-select-trigger-label [icon]="currentType" iconClass="!mr-2 shrink-0">{{ typeLabels[albumsFilters.typeFilter()] | translate }}</app-select-trigger-label>
          </mat-select-trigger>
          @let allIcon = '' | albumTypeIcon;
          @let manualIcon = 'manual' | albumTypeIcon;
          @let smartIcon = 'smart' | albumTypeIcon;
          <mat-option value=""><mat-icon aria-hidden="true" [class]="allIcon.classes">{{ allIcon.text }}</mat-icon>{{ 'albums.type_all' | translate }}</mat-option>
          <mat-option value="manual"><mat-icon aria-hidden="true" [class]="manualIcon.classes">{{ manualIcon.text }}</mat-icon>{{ 'albums.type_manual' | translate }}</mat-option>
          <mat-option value="smart"><mat-icon aria-hidden="true" [class]="smartIcon.classes">{{ smartIcon.text }}</mat-icon>{{ 'albums.type_smart' | translate }}</mat-option>
        </mat-select>
      </mat-form-field>
      <mat-form-field class="!hidden lg:!inline-flex w-40" subscriptSizing="dynamic">
        <mat-label>{{ 'albums.sort_by' | translate }}</mat-label>
        <mat-select [value]="albumsFilters.sort()" (selectionChange)="albumsFilters.sort.set($event.value)">
          <mat-option value="updated_at">{{ 'albums.sort_recent' | translate }}</mat-option>
          <mat-option value="name">{{ 'albums.sort_name' | translate }}</mat-option>
          <mat-option value="photo_count">{{ 'albums.sort_photos' | translate }}</mat-option>
        </mat-select>
      </mat-form-field>
      @if (auth.isEdition()) {
        <button mat-flat-button class="!hidden lg:!inline-flex ml-auto" (click)="albumsFilters.createRequested.set(albumsFilters.createRequested() + 1)">
          <mat-icon>add</mat-icon>
          {{ 'albums.create' | translate }}
        </button>
      }
    </ng-template>

    <h1 id="albums-heading" tabindex="-1" class="sr-only">{{ 'albums.title' | translate }}</h1>
    @if (loading() && !retrying() && albums().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }

    @if ((loadFailed() || retrying()) && albums().length === 0) {
      <div role="alert" class="flex flex-wrap items-center justify-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] text-[var(--mat-sys-on-error-container)] p-4 mb-4">
        <p>{{ (retrying() ? I18N.ui.labels.loading : I18N.albums.list_load_error) | translate }}</p>
        <button mat-stroked-button class="max-lg:!min-h-11" data-albums-retry [attr.aria-disabled]="retrying()" (click)="retryLoad()">{{ (retrying() ? I18N.ui.labels.loading : I18N.gallery.load_error.retry) | translate }}</button>
      </div>
    } @else if (!loadFailed() && albums().length === 0 && !loading()) {
      <div class="text-center py-16 text-[var(--mat-sys-on-surface-variant)]">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ (albumsFilters.search() || albumsFilters.typeFilter() ? I18N.albums.no_matches : I18N.albums.empty) | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      @for (album of albums(); track album.id) {
        <article class="group flex min-w-0 flex-col overflow-hidden rounded-xl bg-[var(--mat-sys-surface-container)] transition-shadow hover:shadow-lg">
        <a [routerLink]="['/album', album.id]" [id]="'album-link-' + album.id"
           class="block min-w-0 cursor-pointer text-[var(--mat-sys-on-surface)] focus-visible:-outline-offset-2">
          @if (album.first_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="album.first_photo_path | thumbnailUrl:320:album.preview_revision" [srcset]="album.first_photo_path | thumbnailSrcset:album.preview_revision" sizes="(min-width: 1536px) 20vw, (min-width: 1024px) 25vw, (min-width: 640px) 34vw, 50vw"
                   alt=""
                   class="w-full h-full object-cover" />
            </div>
          } @else {
            <div class="relative w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
            </div>
          }
          <div class="px-3 pt-2 flex items-start gap-2">
            <div class="flex-1 min-w-0">
              <h2 class="m-0 truncate text-sm font-medium" [title]="album.name">{{ album.name }}</h2>
              @if (album.description) {
                <div class="text-xs text-[var(--mat-sys-on-surface-variant)] truncate">{{ album.description }}</div>
              }
            </div>
            @if (album.is_smart) {
              <mat-icon class="!text-base !w-4 !h-4 shrink-0" [class]="'smart' | markTone"
                        [matTooltip]="'albums.smart_tooltip' | translate"
                        aria-hidden="true">✦</mat-icon>
              <span class="sr-only">{{ 'albums.smart_tooltip' | translate }}</span>
            }
          </div>
        </a>
            <div class="flex items-center justify-between gap-2 px-3 pb-1">
              @if (album.photo_count === null) {
                <span data-album-smart-label class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ 'albums.type_smart' | translate }}</span>
              } @else {
                <span class="text-xs tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ 'albums.photos_count' | translate:{ count: album.photo_count } }}</span>
              }
              @if (!album.is_smart || auth.isEdition()) {
                <button mat-icon-button [matMenuTriggerFor]="albumActions"
                        [id]="'album-actions-' + album.id"
                        [attr.aria-label]="('nav.more' | translate) + ': ' + album.name"><mat-icon>more_horiz</mat-icon></button>
              }
            </div>
            <mat-menu #albumActions="matMenu">
              @if (!album.is_smart) {
                <button mat-menu-item
                        [matTooltip]="'albums.scenes' | translate"
                        [attr.aria-label]="'albums.scenes' | translate"
                        (click)="openScoped('/scenes', album)">
                  <mat-icon>movie_filter</mat-icon>{{ 'albums.scenes' | translate }}
                </button>
              }
              @if (auth.isEdition()) {
                @if (!album.is_smart && proofingEnabled()) {
                  <button mat-menu-item
                          [matTooltip]="'proofing.client_picks' | translate"
                          [attr.aria-label]="'proofing.client_picks' | translate"
                          (click)="openClientPicks(album)">
                    <mat-icon>how_to_vote</mat-icon>{{ 'proofing.client_picks' | translate }}
                  </button>
                }
                <button mat-menu-item
                        [matTooltip]="'albums.cull' | translate"
                        [attr.aria-label]="'albums.cull' | translate"
                        (click)="openScoped('/culling', album)">
                  <mat-icon>auto_delete</mat-icon>{{ 'albums.cull' | translate }}
                </button>
                @if (!album.is_smart && portfolioEnabled()) {
                  <button mat-menu-item
                          [matTooltip]="'albums.portfolio' | translate"
                          [attr.aria-label]="'albums.portfolio' | translate"
                          (click)="exportPortfolio(album)">
                    <mat-icon>web</mat-icon>{{ 'albums.portfolio' | translate }}
                  </button>
                }
                <button mat-menu-item
                        [matTooltip]="'albums.scoring_context.action' | translate"
                        [attr.aria-label]="'albums.scoring_context.action' | translate"
                        (click)="openScoringContext(album)">
                  <mat-icon>tune</mat-icon>{{ 'albums.scoring_context.action' | translate }}
                </button>
                <button mat-menu-item
                        [matTooltip]="'albums.edit' | translate"
                        [attr.aria-label]="'albums.edit' | translate"
                        (click)="editAlbum(album)">
                  <mat-icon>edit</mat-icon>{{ 'albums.edit' | translate }}
                </button>
                <button mat-menu-item
                        [matTooltip]="'albums.share' | translate"
                        [attr.aria-label]="'albums.share' | translate"
                        (click)="shareAlbum(album)">
                  <mat-icon>{{ album.is_shared ? 'link' : 'share' }}</mat-icon>{{ 'albums.share' | translate }}
                </button>
                <button mat-menu-item
                        [matTooltip]="'albums.delete' | translate"
                        [attr.aria-label]="'albums.delete' | translate"
                        (click)="deleteAlbum(album)">
                  <mat-icon>delete</mat-icon>{{ 'albums.delete' | translate }}
                </button>
              }
            </mat-menu>
        </article>
      }
    </div>

    @if ((loadFailed() || retrying()) && albums().length > 0) {
      <div role="alert" class="mt-4 flex flex-wrap items-center justify-center gap-3 rounded-lg bg-[var(--mat-sys-error-container)] p-4 text-[var(--mat-sys-on-error-container)]">
        <p>{{ (retrying() ? I18N.ui.labels.loading : I18N.albums.list_load_error) | translate }}</p>
        <button mat-stroked-button class="max-lg:!min-h-11" data-albums-retry [attr.aria-disabled]="retrying()" (click)="retryLoad()">{{ (retrying() ? I18N.ui.labels.loading : I18N.gallery.load_error.retry) | translate }}</button>
      </div>
    }
    <!-- Infinite scroll sentinel -->
    @if (hasMore() && !loadFailed()) {
      <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-8">
        <mat-spinner diameter="36" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }
  `,
})
export class AlbumsComponent {
  protected readonly I18N = i18nKeys();
  protected readonly typeLabels: Record<AlbumTypeFilter, string> = { '': this.I18N.albums.type_all, manual: this.I18N.albums.type_manual, smart: this.I18N.albums.type_smart };
  private readonly albumService = inject(AlbumService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly latestLoad = new LatestRequest(this.destroyRef);
  private readonly journal = inject(UserActivityJournal);
  private readonly dialog = inject(MatDialog);
  private readonly i18n = inject(I18nService);
  protected readonly auth = inject(AuthService);
  protected readonly albumsFilters = inject(AlbumsFiltersService);
  private readonly router = inject(Router);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly albumsToolbar = viewChild<TemplateRef<unknown>>('albumsToolbar');
  private readonly staleness = inject(StalenessGuardFactory);
  private readonly snack = inject(MatSnackBar);
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);

  protected readonly albums = signal<Album[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly retrying = signal(false);
  private failedReset = true;
  private generation = 0;
  private page = 0;
  private readonly perPage = 48;

  protected readonly hasMore = computed(() => this.albums().length < this.total());
  protected readonly proofingEnabled = computed(() => this.auth.hasFeature('show_proofing'));
  protected readonly portfolioEnabled = computed(() => this.auth.hasFeature('show_portfolio_export'));

  constructor() {
    registerPageContext('albums', () => ({
      search: this.albumsFilters.search(),
      sort: this.albumsFilters.sort(),
      type: this.albumsFilters.typeFilter(),
    }));
    // The assistant's `list_albums show=true` sends the search every time: the page takes exactly that query.
    onPageQuery('/albums', ['search'], query => {
      const search = query.get('search');
      if (search === null) return;
      this.albumsFilters.search.set(search);
      this.albumsFilters.typeFilter.set('');
      this.albumsFilters.sort.set('updated_at');
    });
    this.pageHelp.setDescription('albums.help');
    effect(() => {
      const t = this.albumsToolbar();
      if (t) this.headerSlot.set(t);
    });
    this.destroyRef.onDestroy(() => {
      this.pageHelp.setDescription(null);
      const t = this.albumsToolbar();
      if (t) this.headerSlot.clear(t);
    });
    // Reload when filters change
    effect(() => {
      this.albumsFilters.typeFilter();
      this.albumsFilters.sort();
      this.albumsFilters.search();
      this.auth.identity();
      untracked(() => this.loadAlbums(true));
    });
    // Open the create dialog when the shell's add button increments the counter
    const initialCreate = this.albumsFilters.createRequested();
    effect(() => {
      if (this.albumsFilters.createRequested() !== initialCreate) {
        untracked(() => this.openCreateDialog());
      }
    });
  }

  private async loadAlbums(reset: boolean, restoreFocus = false): Promise<void> {
    const generation = ++this.generation;
    const req = this.latestLoad.begin();
    const requestedPage = reset ? 1 : this.page + 1;
    const params = {
      page: requestedPage,
      per_page: this.perPage,
      type: this.albumsFilters.typeFilter(),
      sort: this.albumsFilters.sort(),
      search: this.albumsFilters.search(),
    };
    const retryButton = restoreFocus ? this.document.querySelector<HTMLButtonElement>('[data-albums-retry]') : null;
    this.retrying.set(restoreFocus);
    const guard = this.staleness.create(this.destroyRef, { requireEdition: false, onNavigate: () => {
      if (generation === this.generation) { this.failedReset = reset; this.loading.set(false); this.loadFailed.set(true); this.retrying.set(false); }
    } });
    const isCurrent = () => generation === this.generation && req.isCurrent() && guard.current()
      && params.type === this.albumsFilters.typeFilter()
      && params.sort === this.albumsFilters.sort()
      && params.search === this.albumsFilters.search();
    if (reset) {
      this.page = 0;
      this.albums.set([]);
      this.total.set(0);
    }
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const res = await firstValueFrom(req.bind(this.albumService.list(params, new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true))));
      if (!isCurrent()) return;
      if (reset) {
        this.albums.set(res.albums);
      } else {
        this.albums.update(prev => [...prev, ...res.albums]);
      }
      // Only successful responses advance the page; a failed append retries it.
      this.page = requestedPage;
      this.total.set(res.total);
      if (restoreFocus && this.document.activeElement === retryButton) {
        const target = res.albums[0]?.id;
        afterNextRender(() => {
          if (generation === this.generation && (this.document.activeElement === this.document.body || this.document.activeElement === retryButton))
            this.document.getElementById(target === undefined ? 'albums-heading' : `album-link-${target}`)?.focus();
        }, { injector: this.injector });
      }
    } catch {
      if (!isCurrent()) return;
      this.failedReset = reset;
      this.loadFailed.set(true);
    } finally {
      if (isCurrent()) { this.loading.set(false); this.retrying.set(false); }
      guard.dispose();
    }
  }

  protected retryLoad(): void { if (!this.loading()) void this.loadAlbums(this.failedReset, true); }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loading() && !this.loadFailed()) {
      void this.loadAlbums(false);
    }
  }

  protected async openCreateDialog(): Promise<void> {
    const guard = new AlbumDialogContext(this.auth, this.router, this.destroyRef);
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    try { const album = await firstValueFrom(ref.afterClosed()); if (album && await guard.settled()) void this.loadAlbums(true); }
    finally { guard.dispose(); }
  }

  /** Open scenes/culling scoped to this album. */
  protected openScoped(path: string, album: Album): void {
    void this.router.navigate([path], { queryParams: { album: album.id } });
  }

  protected async editAlbum(album: Album): Promise<void> {
    const guard = new AlbumDialogContext(this.auth, this.router, this.destroyRef);
    try { const updated = await firstValueFrom(this.dialog.open(EditAlbumDialogComponent, {
      data: { album },
      restoreFocus: `#album-actions-${album.id}`,
      width: '400px',
    }).afterClosed());
    if (updated && await guard.settled()) {
      this.albums.update(list => list.map(a => a.id === updated.id ? updated : a));
    }
    } finally { guard.dispose(); }
  }

  protected async deleteAlbum(album: Album): Promise<void> {
    const guard = new AlbumDialogContext(this.auth, this.router, this.destroyRef);
    try {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: {
        title: this.i18n.t('albums.confirm_delete_title'),
        message: this.i18n.t('albums.confirm_delete_message', { name: album.name }),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed || !await guard.settled()) return;
    const listGeneration = this.generation;
    const filters = [this.albumsFilters.search(), this.albumsFilters.typeFilter(), this.albumsFilters.sort()];
    await firstValueFrom(this.albumService.delete(album.id));
    if (!await guard.settled()) return;
    this.journal.record('album', [], { album_id: album.id, action: 'delete' });
    if (this.generation !== listGeneration || this.loading()
        || filters[0] !== this.albumsFilters.search() || filters[1] !== this.albumsFilters.typeFilter()
        || filters[2] !== this.albumsFilters.sort()) {
      void this.loadAlbums(true);
    } else {
      const wasVisible = this.albums().some(a => a.id === album.id);
      this.albums.update(list => list.filter(a => a.id !== album.id));
      if (wasVisible) this.total.update(t => Math.max(0, t - 1));
    }
    } catch { if (await guard.settled()) this.snack.open(this.i18n.t(I18N.albums.delete_error), '', { duration: 3000 }); }
    finally { guard.dispose(); }
  }

  protected async openScoringContext(album: Album): Promise<void> {
    const guard = this.staleness.create(this.destroyRef);
    try {
    const newContext: string | null | undefined = await firstValueFrom(this.dialog.open(AlbumScoringContextDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: { albumId: album.id, albumName: album.name, currentContext: album.scoring_context } satisfies AlbumScoringContextDialogData,
      width: '95vw',
      maxWidth: '32rem',
      disableClose: true,
    }).afterClosed());
    if (newContext !== undefined && guard.current()) {
      this.albums.update(list => list.map(a => a.id === album.id ? { ...a, scoring_context: newContext } : a));
    }
    } finally { guard.dispose(); }
  }

  protected exportPortfolio(album: Album): void {
    this.dialog.open(PortfolioExportDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: { albumId: album.id, albumName: album.name } satisfies PortfolioExportDialogData,
      width: '460px',
    });
  }

  protected openClientPicks(album: Album): void {
    this.dialog.open(ClientPicksDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: { albumId: album.id, albumName: album.name } satisfies ClientPicksDialogData,
      width: '480px',
    });
  }

  protected async shareAlbum(album: Album): Promise<void> {
    const guard = this.staleness.create(this.destroyRef);
    try {
    await firstValueFrom(this.dialog.open(ShareDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: {
        entityType: 'album',
        entityId: album.id,
        autoGenerate: album.is_shared,
        i18nPrefix: 'albums',
        generateApi: {
          method: 'post',
          url: `/albums/${album.id}/share`,
          body: {},
          extractUrl: (res: Record<string, unknown>) => res['share_url'] as string,
        },
        revokeApi: { url: `/albums/${album.id}/share` },
      } satisfies ShareDialogData,
      width: '400px',
    }).afterClosed());
    if (guard.current()) void this.loadAlbums(true);
    } finally { guard.dispose(); }
  }

}
