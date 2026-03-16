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
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block px-4 pt-2 pb-4 max-w-7xl mx-auto' },
  imports: [
    RouterLink, MatButtonModule, MatIconModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule, MatSnackBarModule,
    TranslatePipe, ThumbnailUrlPipe, InfiniteScrollDirective,
  ],
  template: `
    <div class="flex items-center justify-end mb-3">
      @if (auth.isEdition()) {
        <div class="flex gap-2">
          <!-- Small screen: icon-only buttons -->
          <button mat-icon-button class="sm:!hidden" (click)="autoGenerateAlbums()" [disabled]="autoGenerating()"
                  [matTooltip]="'auto_albums.auto_generate' | translate">
            <mat-icon [class.animate-spin]="autoGenerating()">{{ autoGenerating() ? 'refresh' : 'auto_fix_high' }}</mat-icon>
          </button>
          <button mat-icon-button class="sm:!hidden" (click)="openCreateDialog()"
                  [matTooltip]="'albums.create' | translate">
            <mat-icon>add</mat-icon>
          </button>
          <!-- Larger screens: full buttons with labels -->
          <button mat-stroked-button class="!hidden sm:!inline-flex" (click)="autoGenerateAlbums()" [disabled]="autoGenerating()">
            @if (autoGenerating()) {
              <mat-icon class="animate-spin">refresh</mat-icon>
            } @else {
              <mat-icon>auto_fix_high</mat-icon>
            }
            {{ 'auto_albums.auto_generate' | translate }}
          </button>
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

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
      @for (album of albums(); track album.id) {
        <a [routerLink]="['/album', album.id]"
           class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer">
          @if (album.first_photo_path) {
            <img [src]="album.first_photo_path | thumbnailUrl:320"
                 [alt]="album.name"
                 class="w-full aspect-square object-cover" />
          } @else {
            <div class="w-full aspect-square flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
            </div>
          }
          <div class="p-2">
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
            <div class="flex justify-end gap-0.5 px-1.5 pb-1.5 mt-auto opacity-0 group-hover:opacity-100 transition-opacity">
              <button mat-icon-button
                      class="!w-7 !h-7 !p-0"
                      [matTooltip]="'albums.edit' | translate"
                      (click)="editAlbum($event, album)">
                <mat-icon class="!text-sm !w-4 !h-4 !leading-4 opacity-60">edit</mat-icon>
              </button>
              <button mat-icon-button
                      class="!w-7 !h-7 !p-0"
                      [matTooltip]="'albums.share' | translate"
                      (click)="shareAlbum($event, album)">
                <mat-icon class="!text-sm !w-4 !h-4 !leading-4 opacity-60">{{ album.is_shared ? 'link' : 'share' }}</mat-icon>
              </button>
              <button mat-icon-button
                      class="!w-7 !h-7 !p-0"
                      [matTooltip]="'albums.delete' | translate"
                      (click)="deleteAlbum($event, album)">
                <mat-icon class="!text-sm !w-4 !h-4 !leading-4 opacity-60">delete</mat-icon>
              </button>
            </div>
          }
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
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  protected readonly auth = inject(AuthService);
  private readonly albumsFilters = inject(AlbumsFiltersService);

  protected readonly albums = signal<Album[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly autoGenerating = signal(false);

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
    if (updated) this.loadAlbums(true);
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

  protected async autoGenerateAlbums(): Promise<void> {
    const { AutoAlbumSettingsDialogComponent } = await import('./auto-album-settings-dialog.component');
    const ref = this.dialog.open(AutoAlbumSettingsDialogComponent, {
      width: '95vw',
      maxWidth: '400px',
    });
    const settings = await firstValueFrom(ref.afterClosed());
    if (!settings) return;

    this.autoGenerating.set(true);
    try {
      const result = await firstValueFrom(this.albumService.autoGenerate(false, settings));
      this.snackBar.open(
        this.i18n.t('auto_albums.auto_generated', { count: result.albums_created }),
        '', { duration: 3000, horizontalPosition: 'right', verticalPosition: 'bottom' },
      );
      await this.loadAlbums(true);
    } catch {
      this.snackBar.open(this.i18n.t('auto_albums.error_generating'), '', { duration: 3000 });
    } finally {
      this.autoGenerating.set(false);
    }
  }
}
