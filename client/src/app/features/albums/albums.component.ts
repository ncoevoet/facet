import { Component, inject, signal, computed, effect, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { EditAlbumDialogComponent } from './edit-album-dialog.component';
import { AlbumsFiltersService } from './albums-filters.service';
import { ShareDialogComponent, ShareDialogData } from '../../shared/components/share-dialog/share-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block px-4 pt-4 pb-4' },
  imports: [
    RouterLink, MatButtonModule, MatIconModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule,
    TranslatePipe, ThumbnailUrlPipe, InfiniteScrollDirective,
  ],
  template: `
    <div class="flex items-center justify-start mb-3">
      @if (auth.isEdition()) {
        <div class="flex gap-2">
          <!-- Small screen: icon-only buttons -->
          <button mat-icon-button class="sm:!hidden" (click)="openCreateDialog()"
                  [matTooltip]="'albums.create' | translate">
            <mat-icon>add</mat-icon>
          </button>
          <!-- Larger screens: full buttons with labels -->
          <button mat-flat-button class="!hidden sm:!inline-flex" (click)="openCreateDialog()">
            <mat-icon>add</mat-icon>
            {{ 'albums.create' | translate }}
          </button>
        </div>
      }
    </div>

    @if (loading() && albums().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    @if (albums().length === 0 && !loading()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ 'albums.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (album of albums(); track album.id) {
        <a [routerLink]="['/album', album.id]"
           class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer">
          @if (album.first_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="album.first_photo_path | thumbnailUrl:320"
                   [alt]="album.name"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
            </div>
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
            </div>
          }
          <div class="p-3 flex items-start gap-1">
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm truncate inline-flex items-center gap-1">
                {{ album.name }}
                @if (album.is_smart) {
                  <mat-icon class="!text-xs !w-3 !h-3 !leading-3">auto_awesome</mat-icon>
                }
              </div>
              @if (album.description) {
                <div class="text-xs opacity-60 truncate">{{ album.description }}</div>
              }
            </div>
            @if (auth.isEdition()) {
              <div class="flex items-center shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button mat-icon-button
                        [matTooltip]="'albums.edit' | translate"
                        (click)="editAlbum($event, album)">
                  <mat-icon class="opacity-60">edit</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="'albums.share' | translate"
                        (click)="shareAlbum($event, album)">
                  <mat-icon class="opacity-60">{{ album.is_shared ? 'link' : 'share' }}</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="'albums.delete' | translate"
                        (click)="deleteAlbum($event, album)">
                  <mat-icon class="opacity-60">delete</mat-icon>
                </button>
              </div>
            }
          </div>
        </a>
      }
    </div>

    <!-- Infinite scroll sentinel -->
    @if (hasMore()) {
      <div appInfiniteScroll (scrollReached)="onScrollReached()" class="flex justify-center py-8">
        <mat-spinner diameter="36" />
      </div>
    }
  `,
})
export class AlbumsComponent {
  private readonly albumService = inject(AlbumService);
  private readonly dialog = inject(MatDialog);
  private readonly i18n = inject(I18nService);
  protected readonly auth = inject(AuthService);
  private readonly albumsFilters = inject(AlbumsFiltersService);

  protected readonly albums = signal<Album[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  private page = 1;
  private readonly perPage = 48;

  protected readonly hasMore = computed(() => this.albums().length < this.total());

  constructor() {
    // Reload when filters change
    effect(() => {
      this.albumsFilters.typeFilter();
      this.albumsFilters.sort();
      this.albumsFilters.search();
      untracked(() => this.loadAlbums(true));
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
    this.albums.update(list => list.filter(a => a.id !== album.id));
    this.total.update(t => t - 1);
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
