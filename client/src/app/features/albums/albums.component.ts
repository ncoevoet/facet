import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block p-4 max-w-7xl mx-auto' },
  imports: [
    RouterLink, MatButtonModule, MatIconModule, MatDialogModule,
    TranslatePipe, ThumbnailUrlPipe,
  ],
  template: `
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-semibold">{{ 'albums.title' | translate }}</h1>
      @if (auth.isEdition()) {
        <button mat-flat-button (click)="openCreateDialog()">
          <mat-icon>add</mat-icon>
          {{ 'albums.create' | translate }}
        </button>
      }
    </div>

    @if (albums().length === 0 && !loading()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ 'albums.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
      @for (album of albums(); track album.id) {
        <a [routerLink]="['/album', album.id]"
           class="group relative rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer">
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
            <button mat-icon-button
                    class="!absolute top-1 right-1 !w-7 !h-7 !p-0 opacity-0 group-hover:opacity-100 transition-opacity bg-black/50"
                    (click)="deleteAlbum($event, album)">
              <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-white">delete</mat-icon>
            </button>
          }
        </a>
      }
    </div>
  `,
})
export class AlbumsComponent implements OnInit {
  private albumService = inject(AlbumService);
  private dialog = inject(MatDialog);
  private i18n = inject(I18nService);
  readonly auth = inject(AuthService);

  readonly albums = signal<Album[]>([]);
  readonly loading = signal(false);

  async ngOnInit(): Promise<void> {
    await this.loadAlbums();
  }

  async loadAlbums(): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(this.albumService.list());
      this.albums.set(res.albums);
    } finally {
      this.loading.set(false);
    }
  }

  openCreateDialog(): void {
    const ref = this.dialog.open(CreateAlbumDialogComponent, { width: '400px' });
    ref.afterClosed().subscribe((album: Album | undefined) => {
      if (album) this.loadAlbums();
    });
  }

  async deleteAlbum(event: Event, album: Album): Promise<void> {
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
  }
}
