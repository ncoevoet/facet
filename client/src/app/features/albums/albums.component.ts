import { Component, inject, signal, computed, effect, untracked, viewChild, TemplateRef, DestroyRef } from '@angular/core';
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
import { AlbumService, Album } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { CreateAlbumDialogComponent } from './create-album-dialog.component';
import { EditAlbumDialogComponent } from './edit-album-dialog.component';
import { ClientPicksDialogComponent, ClientPicksDialogData } from './client-picks-dialog.component';
import { AlbumsFiltersService } from './albums-filters.service';
import { ShareDialogComponent, ShareDialogData } from '../../shared/components/share-dialog/share-dialog.component';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { I18N } from '../../core/i18n/keys';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';

@Component({
  selector: 'app-albums',
  standalone: true,
  host: { class: 'block px-4 pt-4 pb-4' },
  imports: [
    RouterLink, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule,
    MatSelectModule, MatDialogModule, MatTooltipModule,
    MatProgressSpinnerModule,
    TranslatePipe, ThumbnailUrlPipe, InfiniteScrollDirective,
  ],
  template: `
    <ng-template #albumsToolbar>
      <mat-form-field class="!hidden lg:!inline-flex w-52" subscriptSizing="dynamic">
        <mat-label>{{ I18N.albums.search | translate }}</mat-label>
        <input matInput [value]="albumsFilters.search()" (input)="albumsFilters.search.set($any($event.target).value)" />
        <mat-icon matPrefix class="opacity-60">search</mat-icon>
      </mat-form-field>
      <mat-form-field class="!hidden lg:!inline-flex w-36" subscriptSizing="dynamic">
        <mat-label>{{ I18N.albums.filter_type | translate }}</mat-label>
        <mat-select [value]="albumsFilters.typeFilter()" (selectionChange)="albumsFilters.typeFilter.set($event.value)">
          <mat-option value="">{{ I18N.albums.type_all | translate }}</mat-option>
          <mat-option value="manual">{{ I18N.albums.type_manual | translate }}</mat-option>
          <mat-option value="smart">{{ I18N.albums.type_smart | translate }}</mat-option>
        </mat-select>
      </mat-form-field>
      <mat-form-field class="!hidden lg:!inline-flex w-40" subscriptSizing="dynamic">
        <mat-label>{{ I18N.albums.sort_by | translate }}</mat-label>
        <mat-select [value]="albumsFilters.sort()" (selectionChange)="albumsFilters.sort.set($event.value)">
          <mat-option value="updated_at">{{ I18N.albums.sort_recent | translate }}</mat-option>
          <mat-option value="name">{{ I18N.albums.sort_name | translate }}</mat-option>
          <mat-option value="photo_count">{{ I18N.albums.sort_photos | translate }}</mat-option>
        </mat-select>
      </mat-form-field>
      @if (auth.isEdition()) {
        <button mat-icon-button class="!hidden lg:!inline-flex" [matTooltip]="I18N.albums.create | translate" [attr.aria-label]="I18N.albums.create | translate" (click)="albumsFilters.createRequested.set(albumsFilters.createRequested() + 1)">
          <mat-icon>add</mat-icon>
        </button>
      }
    </ng-template>

    @if (loading() && albums().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    @if (albums().length === 0 && !loading()) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">photo_library</mat-icon>
        <p>{{ I18N.albums.empty | translate }}</p>
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
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ album.name }}</span>
                @if (album.is_smart) {
                  <mat-icon class="!text-xs !w-3 !h-3 !leading-3 text-white/80 shrink-0 pointer-events-auto"
                            [matTooltip]="I18N.albums.smart_tooltip | translate"
                            [attr.aria-label]="I18N.albums.smart_tooltip | translate">auto_awesome</mat-icon>
                }
              </div>
            </div>
          } @else {
            <div class="relative w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">photo_library</mat-icon>
              <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                <span class="text-white text-xs font-medium truncate">{{ album.name }}</span>
                @if (album.is_smart) {
                  <mat-icon class="!text-xs !w-3 !h-3 !leading-3 text-white/80 shrink-0 pointer-events-auto"
                            [matTooltip]="I18N.albums.smart_tooltip | translate"
                            [attr.aria-label]="I18N.albums.smart_tooltip | translate">auto_awesome</mat-icon>
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
                        [matTooltip]="I18N.albums.scenes | translate"
                        (click)="openScoped($event, '/scenes', album)">
                  <mat-icon class="opacity-60">movie_filter</mat-icon>
                </button>
              }
              @if (auth.isEdition()) {
                @if (!album.is_smart && proofingEnabled()) {
                  <button mat-icon-button
                          [matTooltip]="I18N.proofing.client_picks | translate"
                          (click)="openClientPicks($event, album)">
                    <mat-icon class="opacity-60">how_to_vote</mat-icon>
                  </button>
                }
                <button mat-icon-button
                        [matTooltip]="I18N.albums.cull | translate"
                        (click)="openScoped($event, '/culling', album)">
                  <mat-icon class="opacity-60">auto_delete</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="I18N.albums.edit | translate"
                        (click)="editAlbum($event, album)">
                  <mat-icon class="opacity-60">edit</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="I18N.albums.share | translate"
                        (click)="shareAlbum($event, album)">
                  <mat-icon class="opacity-60">{{ album.is_shared ? 'link' : 'share' }}</mat-icon>
                </button>
                <button mat-icon-button
                        [matTooltip]="I18N.albums.delete | translate"
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
        <mat-spinner diameter="36" />
      </div>
    }
  `,
})
export class AlbumsComponent {
  protected readonly I18N = I18N;
  private readonly albumService = inject(AlbumService);
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

  constructor() {
    this.pageHelp.setDescription(I18N.albums.help);
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
        title: this.i18n.t(I18N.albums.confirm_delete_title),
        message: this.i18n.t(I18N.albums.confirm_delete_message, { name: album.name }),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;
    await firstValueFrom(this.albumService.delete(album.id));
    this.albums.update(list => list.filter(a => a.id !== album.id));
    this.total.update(t => t - 1);
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
