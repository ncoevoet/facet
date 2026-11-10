import { Component, inject, signal, computed, effect, untracked, viewChild, TemplateRef, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { LatestRequest } from '../../shared/utils/latest-request';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { EditAlbumDialogComponent } from './edit-album-dialog.component';
import { ClientPicksDialogComponent, ClientPicksDialogData } from './client-picks-dialog.component';
import { PortfolioExportDialogComponent, PortfolioExportDialogData } from './portfolio-export-dialog.component';
import { AlbumScoringContextDialogComponent, AlbumScoringContextDialogData } from './album-scoring-context-dialog.component';
import { AlbumsFiltersService } from './albums-filters.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { registerPageContext } from '../../core/agent/page-context.service';
import { ShareDialogComponent, ShareDialogData } from '../../shared/components/share-dialog/share-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { onPageQuery } from '../../shared/utils/page-query';
import { MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block px-4 pt-4 pb-4' },
  imports: [
    MarkTonePipe,
    RouterLink, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule,
    MatSelectModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule,
    TranslatePipe, ThumbnailUrlPipe, InfiniteScrollDirective,
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
          <mat-option value="">{{ 'albums.type_all' | translate }}</mat-option>
          <mat-option value="manual">{{ 'albums.type_manual' | translate }}</mat-option>
          <mat-option value="smart">{{ 'albums.type_smart' | translate }}</mat-option>
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
        <button mat-icon-button class="!hidden lg:!inline-flex" [matTooltip]="'albums.create' | translate" [attr.aria-label]="'albums.create' | translate" (click)="albumsFilters.createRequested.set(albumsFilters.createRequested() + 1)">
          <mat-icon>add</mat-icon>
        </button>
      }
    </ng-template>

    @if (loading() && albums().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }

    @if (albums().length === 0 && !loading() && !loadError()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ 'albums.empty' | translate }}</p>
      </div>
    }

    @if (loadError() && !loading()) {
      <div role="alert" class="flex items-center justify-center gap-3 py-10 text-sm">
        <span>{{ 'errors.server_error' | translate }}</span>
        <button mat-stroked-button (click)="loadAlbums(true)">{{ 'gallery.load_error.retry' | translate }}</button>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (album of albums(); track album.id) {
        <a [routerLink]="['/album', album.id]"
           class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer">
          @if (album.first_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="album.first_photo_path | thumbnailUrl:320:album.preview_revision"
                   [alt]="album.name"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ album.name }}</span>
                @if (album.is_smart) {
                  <mat-icon class="!text-xs !w-3 !h-3 !leading-3 shrink-0 pointer-events-auto" [class]="'smart' | markTone"
                            [matTooltip]="'albums.smart_tooltip' | translate"
                            [attr.aria-label]="'albums.smart_tooltip' | translate">✦</mat-icon>
                }
              </div>
            </div>
          } @else {
            <div class="relative w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ album.name }}</span>
                @if (album.is_smart) {
                  <mat-icon class="!text-xs !w-3 !h-3 !leading-3 shrink-0 pointer-events-auto" [class]="'smart' | markTone"
                            [matTooltip]="'albums.smart_tooltip' | translate"
                            [attr.aria-label]="'albums.smart_tooltip' | translate">✦</mat-icon>
                }
              </div>
            </div>
          }
          <div class="p-3 flex items-start gap-1">
            <div class="flex-1 min-w-0">
              @if (album.description) {
                <div class="text-xs opacity-60 truncate">{{ album.description }}</div>
              }
            </div>
            <div class="flex items-center shrink-0">
              @if (!album.is_smart) {
                <button mat-icon-button
                        [matTooltip]="'albums.scenes' | translate"
                        [attr.aria-label]="'albums.scenes' | translate"
                        (click)="openScoped($event, '/scenes', album)">
                  <mat-icon class="opacity-60">movie_filter</mat-icon>
                </button>
              }
              @if (auth.isEdition()) {
                @if (!album.is_smart && proofingEnabled()) {
                  <button mat-icon-button
                          [matTooltip]="'proofing.client_picks' | translate"
                          [attr.aria-label]="'proofing.client_picks' | translate"
                          (click)="openClientPicks($event, album)">
                    <mat-icon class="opacity-60">how_to_vote</mat-icon>
                  </button>
                }
                <button mat-icon-button
                        [matTooltip]="'albums.cull' | translate"
                        [attr.aria-label]="'albums.cull' | translate"
                        (click)="openScoped($event, '/culling', album)">
                  <mat-icon class="opacity-60">auto_delete</mat-icon>
                </button>
                @if (!album.is_smart && portfolioEnabled()) {
                  <button mat-icon-button
                          [matTooltip]="'albums.portfolio' | translate"
                          [attr.aria-label]="'albums.portfolio' | translate"
                          (click)="exportPortfolio($event, album)">
                    <mat-icon class="opacity-60">web</mat-icon>
                  </button>
                }
                <button mat-icon-button
                        [matTooltip]="'albums.scoring_context.action' | translate"
                        [attr.aria-label]="'albums.scoring_context.action' | translate"
                        (click)="openScoringContext($event, album)">
                  <mat-icon class="opacity-60">tune</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="'albums.edit' | translate"
                        [attr.aria-label]="'albums.edit' | translate"
                        (click)="editAlbum($event, album)">
                  <mat-icon class="opacity-60">edit</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="'albums.share' | translate"
                        [attr.aria-label]="'albums.share' | translate"
                        (click)="shareAlbum($event, album)">
                  <mat-icon class="opacity-60">{{ album.is_shared ? 'link' : 'share' }}</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="'albums.delete' | translate"
                        [attr.aria-label]="'albums.delete' | translate"
                        (click)="deleteAlbum($event, album)">
                  <mat-icon class="opacity-60">delete</mat-icon>
                </button>
              }
            </div>
          </div>
        </a>
      }
    </div>

    <!-- Infinite scroll sentinel -->
    @if (hasMore()) {
      <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-8">
        <mat-spinner diameter="36" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }
  `,
})
export class AlbumsComponent {
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

  protected readonly albums = signal<Album[]>([]);
  protected readonly total = signal(0);
  /** A failed load: the empty state must not read as "you have no albums". */
  protected readonly loadError = signal(false);
  protected readonly loading = signal(false);
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

  private async loadAlbums(reset: boolean): Promise<void> {
    const req = this.latestLoad.begin();
    const requestedPage = reset ? 1 : this.page + 1;
    const params = {
      page: requestedPage,
      per_page: this.perPage,
      type: this.albumsFilters.typeFilter(),
      sort: this.albumsFilters.sort(),
      search: this.albumsFilters.search(),
    };
    const isCurrent = () => req.isCurrent()
      && params.type === this.albumsFilters.typeFilter()
      && params.sort === this.albumsFilters.sort()
      && params.search === this.albumsFilters.search();
    if (reset) {
      this.page = 0;
      this.albums.set([]);
      this.total.set(0);
    }
    this.loadError.set(false);
    this.loading.set(true);
    try {
      const res = await firstValueFrom(req.bind(this.albumService.list(params)));
      if (!isCurrent()) return;
      if (reset) {
        this.albums.set(res.albums);
      } else {
        this.albums.update(prev => [...prev, ...res.albums]);
      }
      // Only successful responses advance the page; a failed append retries it.
      this.page = requestedPage;
      this.total.set(res.total);
    } catch {
      if (isCurrent()) this.loadError.set(true);
    } finally {
      if (isCurrent()) this.loading.set(false);
    }
  }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loading()) {
      void this.loadAlbums(false);
    }
  }

  protected async openCreateDialog(): Promise<void> {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    const album = await firstValueFrom(ref.afterClosed());
    if (album) this.loadAlbums(true);
  }

  /** Open scenes/culling scoped to this album (card is an anchor — stop its nav). */
  protected openScoped(event: Event, path: string, album: Album): void {
    event.preventDefault();
    event.stopPropagation();
    void this.router.navigate([path], { queryParams: { album: album.id } });
  }

  protected async editAlbum(event: Event, album: Album): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    const updated = await firstValueFrom(this.dialog.open(EditAlbumDialogComponent, {
      data: { album },
      width: '400px',
    }).afterClosed());
    if (updated) {
      this.albums.update(list => list.map(a => a.id === updated.id ? updated : a));
    }
  }

  protected async deleteAlbum(event: Event, album: Album): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t('albums.confirm_delete_title'),
        message: this.i18n.t('albums.confirm_delete_message', { name: album.name }),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;
    await firstValueFrom(this.albumService.delete(album.id));
    this.journal.record('album', [], { album_id: album.id, action: 'delete' });
    this.albums.update(list => list.filter(a => a.id !== album.id));
    this.total.update(t => t - 1);
  }

  protected async openScoringContext(event: Event, album: Album): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    const newContext: string | null | undefined = await firstValueFrom(this.dialog.open(AlbumScoringContextDialogComponent, {
      data: { albumId: album.id, albumName: album.name, currentContext: album.scoring_context } satisfies AlbumScoringContextDialogData,
      width: '95vw',
      maxWidth: '32rem',
      disableClose: true,
    }).afterClosed());
    if (newContext !== undefined) {
      this.albums.update(list => list.map(a => a.id === album.id ? { ...a, scoring_context: newContext } : a));
    }
  }

  protected exportPortfolio(event: Event, album: Album): void {
    event.preventDefault();
    event.stopPropagation();
    this.dialog.open(PortfolioExportDialogComponent, {
      data: { albumId: album.id, albumName: album.name } satisfies PortfolioExportDialogData,
      width: '460px',
    });
  }

  protected openClientPicks(event: Event, album: Album): void {
    event.preventDefault();
    event.stopPropagation();
    this.dialog.open(ClientPicksDialogComponent, {
      data: { albumId: album.id, albumName: album.name } satisfies ClientPicksDialogData,
      width: '480px',
    });
  }

  protected async shareAlbum(event: Event, album: Album): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    await firstValueFrom(this.dialog.open(ShareDialogComponent, {
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
    this.loadAlbums(true);
  }

}
