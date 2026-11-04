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
import { MatMenuModule } from '@angular/material/menu';
import { firstValueFrom } from 'rxjs';
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
    RouterLink, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule,
    MatSelectModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule, MatMenuModule, MarkTonePipe,
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

    <h1 class="m-0 mb-4 text-lg font-medium text-[var(--mat-sys-on-surface)]">{{ 'albums.title' | translate }}</h1>
    @if (loading() && albums().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="'ui.labels.loading' | translate" />
      </div>
    }

    @if (albums().length === 0 && !loading()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ 'albums.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      @for (album of albums(); track album.id) {
        <article class="min-w-0">
        <a [routerLink]="['/album', album.id]"
           class="group block min-w-0 rounded-sm overflow-hidden cursor-pointer text-[var(--mat-sys-on-surface)]">
          @if (album.first_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="album.first_photo_path | thumbnailUrl:320:album.preview_revision"
                   [alt]="album.name"
                   class="w-full h-full object-cover" />
            </div>
          } @else {
            <div class="relative w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
            </div>
          }
          <div class="pt-2 flex items-start gap-2">
            <div class="flex-1 min-w-0">
              <h2 class="m-0 truncate text-sm font-medium" [title]="album.name">{{ album.name }}</h2>
              @if (album.description) {
                <div class="text-xs text-[var(--mat-sys-on-surface-variant)] truncate">{{ album.description }}</div>
              }
            </div>
            @if (album.is_smart) {
              <mat-icon class="!text-base !w-4 !h-4 shrink-0" [class]="'smart' | markTone"
                        [matTooltip]="'albums.smart_tooltip' | translate"
                        [attr.aria-label]="'albums.smart_tooltip' | translate">✦</mat-icon>
            }
          </div>
        </a>
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs tabular-nums text-[var(--mat-sys-on-surface-variant)]">{{ 'albums.photos_count' | translate:{ count: album.photo_count } }}</span>
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
  protected readonly loading = signal(false);
  private page = 1;
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
    inject(DestroyRef).onDestroy(() => {
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
    if (reset) {
      this.page = 1;
      this.albums.set([]);
    }
    this.loading.set(true);
    try {
      const params: Record<string, string | number> = {
        page: this.page,
        per_page: this.perPage,
        type: this.albumsFilters.typeFilter(),
        sort: this.albumsFilters.sort(),
        search: this.albumsFilters.search(),
      };
      const res = await firstValueFrom(this.albumService.list(params));
      if (reset) {
        this.albums.set(res.albums);
      } else {
        this.albums.update(prev => [...prev, ...res.albums]);
      }
      this.total.set(res.total);
    } catch {
      if (reset) {
        this.albums.set([]);
        this.total.set(0);
      }
    } finally {
      this.loading.set(false);
    }
  }

  protected onScrollReached(): void {
    if (this.hasMore() && !this.loading()) {
      this.page++;
      this.loadAlbums(false);
    }
  }

  protected async openCreateDialog(): Promise<void> {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    const album = await firstValueFrom(ref.afterClosed());
    if (album) this.loadAlbums(true);
  }

  /** Open scenes/culling scoped to this album. */
  protected openScoped(path: string, album: Album): void {
    void this.router.navigate([path], { queryParams: { album: album.id } });
  }

  protected async editAlbum(album: Album): Promise<void> {
    const updated = await firstValueFrom(this.dialog.open(EditAlbumDialogComponent, {
      data: { album },
      restoreFocus: `#album-actions-${album.id}`,
      width: '400px',
    }).afterClosed());
    if (updated) {
      this.albums.update(list => list.map(a => a.id === updated.id ? updated : a));
    }
  }

  protected async deleteAlbum(album: Album): Promise<void> {
    const ref = this.dialog.open(ConfirmDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
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

  protected async openScoringContext(album: Album): Promise<void> {
    const newContext: string | null | undefined = await firstValueFrom(this.dialog.open(AlbumScoringContextDialogComponent, {
      restoreFocus: `#album-actions-${album.id}`,
      data: { albumId: album.id, albumName: album.name, currentContext: album.scoring_context } satisfies AlbumScoringContextDialogData,
      width: '95vw',
      maxWidth: '32rem',
      disableClose: true,
    }).afterClosed());
    if (newContext !== undefined) {
      this.albums.update(list => list.map(a => a.id === album.id ? { ...a, scoring_context: newContext } : a));
    }
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
    this.loadAlbums(true);
  }

}
