import { Component, inject, signal, computed, OnInit, DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, ActivatedRoute } from '@angular/router';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

interface FolderItem {
  name: string;
  path: string;
  photo_count: number;
  cover_photo_path: string | null;
}

interface FoldersResponse {
  folders: FolderItem[];
  has_direct_photos: boolean;
}

@Component({
  selector: 'app-folders',
  standalone: true,
  imports: [
    DecimalPipe,
    MatIconModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    TranslatePipe,
    ThumbnailUrlPipe,
  ],
  host: { class: 'block px-4 pt-4 pb-4' },
  template: `
    @if (loading() && folders().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    <!-- Breadcrumb -->
    @if (breadcrumbs().length > 0) {
      <nav class="flex items-center gap-1 text-sm mb-3 flex-wrap">
        <button mat-button class="!min-w-0 !px-2" (click)="navigateTo('')">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">home</mat-icon>
          {{ 'folders.root' | translate }}
        </button>
        @for (crumb of breadcrumbs(); track crumb.path) {
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40">chevron_right</mat-icon>
          @if (!$last) {
            <button mat-button class="!min-w-0 !px-2" (click)="navigateTo(crumb.path)">
              {{ crumb.name }}
            </button>
          } @else {
            <span class="px-2 font-medium">{{ crumb.name }}</span>
          }
        }
      </nav>
    }

    @if (!loading() && folders().length === 0) {
      <div class="text-center py-16 opacity-60">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">folder_off</mat-icon>
        <p>{{ 'folders.empty' | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (folder of folders(); track folder.path) {
        <button
          class="group flex flex-col rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
          (click)="openFolder(folder)">
          @if (folder.cover_photo_path) {
            <div class="relative w-full aspect-[4/3] overflow-hidden">
              <img [src]="folder.cover_photo_path | thumbnailUrl:320"
                   [alt]="folder.name"
                   loading="lazy"
                   class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
            </div>
          } @else {
            <div class="w-full aspect-[4/3] flex items-center justify-center bg-[var(--mat-sys-surface-container-high)]">
              <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">folder</mat-icon>
            </div>
          }
          <div class="p-3">
            <div class="font-medium text-sm truncate">{{ folder.name }}</div>
            <div class="text-xs opacity-60">{{ folder.photo_count | number }} {{ 'folders.photos_count' | translate }}</div>
          </div>
        </button>
      }
    </div>
  `,
})
export class FoldersComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly folders = signal<FolderItem[]>([]);
  protected readonly loading = signal(false);
  protected readonly currentPrefix = signal('');

  protected readonly breadcrumbs = computed(() => {
    const prefix = this.currentPrefix();
    if (!prefix) return [];
    const parts = prefix.replace(/\/$/, '').split('/').filter(Boolean);
    const crumbs: { name: string; path: string }[] = [];
    for (let i = 0; i < parts.length; i++) {
      crumbs.push({
        name: parts[i],
        path: parts.slice(0, i + 1).join('/') + '/',
      });
    }
    return crumbs;
  });

  ngOnInit(): void {
    this.route.queryParams.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      this.currentPrefix.set(params['prefix'] || '');
      this.loadFolders();
    });
  }

  private async loadFolders(): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<FoldersResponse>('/folders', {
          prefix: this.currentPrefix(),
        }),
      );
      // Auto-redirect to gallery if no subfolders (leaf directory)
      // replaceUrl avoids a back-button loop (back → leaf folder → redirect → gallery → …)
      if (res.folders.length === 0 && this.currentPrefix()) {
        this.router.navigate(['/'], {
          queryParams: {
            path_prefix: this.currentPrefix(),
            sort: 'date_taken',
            sort_direction: 'DESC',
          },
          replaceUrl: true,
        });
        return;
      }
      this.folders.set(res.folders);
    } finally {
      this.loading.set(false);
    }
  }

  protected navigateTo(prefix: string): void {
    this.router.navigate(['/folders'], {
      queryParams: prefix ? { prefix } : {},
    });
  }

  protected openFolder(folder: FolderItem): void {
    this.router.navigate(['/folders'], {
      queryParams: { prefix: folder.path },
    });
  }
}
