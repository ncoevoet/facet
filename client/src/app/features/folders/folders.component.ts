import { Component, inject, signal, computed, effect, OnInit, OnDestroy, DestroyRef, ChangeDetectionStrategy, TemplateRef, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, ActivatedRoute } from '@angular/router';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ThumbnailSrcsetPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { buildFolderBreadcrumbs, type FolderItem, type FoldersResponse } from './folders.util';
import { GalleryStore } from '../gallery/gallery.store';

/** History-state flag set by a breadcrumb: the user chose this level, so a lone folder is not skipped. */
export const KEEP_CHAIN_STATE = 'foldersKeepChain';

@Component({
  selector: 'app-folders',
  standalone: true,
  imports: [
    DecimalPipe,
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    ThumbnailSrcsetPipe,
  ],
  host: { class: 'block px-4 pt-4 pb-4' },
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h1 class="sr-only">{{ I18N.folders.title | translate }}</h1>
    <!-- Breadcrumb: lg+ renders it in the shell's page-actions bar (HeaderSlotService);
         below lg the same template renders here as a sticky row. Always rendered, so its
         height is constant while the lone-folder redirect hops resolve. -->
    <ng-template #foldersToolbar>
      <nav class="flex items-center gap-1 text-sm min-w-0 overflow-x-auto whitespace-nowrap" [attr.aria-label]="I18N.folders.title | translate">
        <button mat-button class="!min-w-0 !px-2 shrink-0" (click)="navigateTo('')">
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 mr-1">home</mat-icon>
          {{ I18N.folders.root | translate }}
        </button>
        @for (crumb of breadcrumbs(); track crumb.path) {
          <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-40 shrink-0">chevron_right</mat-icon>
          @if (!$last) {
            <button mat-button class="!min-w-0 !px-2 shrink-0" (click)="navigateTo(crumb.path)">
              {{ crumb.name }}
            </button>
          } @else {
            <span class="px-2 font-medium">{{ crumb.name }}</span>
          }
        }
      </nav>
    </ng-template>
    <div data-folders-toolbar class="lg:hidden sticky top-0 z-20 -mx-4 -mt-4 mb-3 px-4 py-1 bg-[var(--mat-sys-surface)] border-b border-[var(--mat-sys-outline-variant)]">
      <ng-container [ngTemplateOutlet]="foldersToolbar" />
    </div>

    @if (loading() && folders().length === 0) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" [attr.aria-label]="I18N.ui.labels.loading | translate" />
      </div>
    }

    @if (!loading() && folders().length === 0) {
      <div class="text-center py-16 text-[var(--mat-sys-on-surface-variant)]">
        <mat-icon class="!text-5xl !w-12 !h-12 mb-4">folder_off</mat-icon>
        <p>{{ I18N.folders.empty | translate }}</p>
      </div>
    }

    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      @for (folder of folders(); track folder.path) {
        <div class="relative">
          <button
            class="group flex flex-col w-full rounded-xl overflow-hidden bg-[var(--mat-sys-surface-container)] hover:shadow-lg transition-shadow cursor-pointer text-left"
            (click)="openFolder(folder)">
            @if (folder.cover_photo_path) {
              <div class="relative w-full aspect-[4/3] overflow-hidden">
                <img [src]="folder.cover_photo_path | thumbnailUrl:320:folder.preview_revision" [srcset]="folder.cover_photo_path | thumbnailSrcset:folder.preview_revision" sizes="(min-width: 1280px) 17vw, (min-width: 1024px) 20vw, (min-width: 768px) 25vw, (min-width: 640px) 34vw, 50vw"
                     [alt]="folder.name"
                     loading="lazy"
                     class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                  <span class="text-white text-xs font-medium truncate">{{ folder.name }}</span>
                </div>
              </div>
            } @else {
              <div class="relative w-full aspect-[4/3] flex items-center justify-center overflow-hidden bg-[var(--mat-sys-surface-container-high)]">
                <mat-icon class="!text-4xl !w-10 !h-10 opacity-30">folder</mat-icon>
                <div class="absolute inset-x-0 top-0 z-[5] flex items-start gap-1 bg-gradient-to-b from-black/70 to-transparent px-2 pt-1.5 pb-4 pointer-events-none">
                  <span class="text-white text-xs font-medium truncate">{{ folder.name }}</span>
                </div>
              </div>
            }
            <div class="p-3">
              <div class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ folder.photo_count | number }} {{ I18N.folders.photos_count | translate }}</div>
            </div>
          </button>
          <button
            mat-icon-button
            class="!absolute top-0.5 right-0.5 z-10 !text-white !bg-black/40"
            [matTooltip]="I18N.folders.filter_gallery | translate"
            [attr.aria-label]="(I18N.folders.filter_gallery | translate) + ' — ' + folder.name"
            (click)="filterInGallery(folder)">
            <mat-icon class="!text-base !w-5 !h-5 !leading-5">filter_alt</mat-icon>
          </button>
        </div>
      }
    </div>
  `,
})
export class FoldersComponent implements OnInit, OnDestroy {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly pageHelp = inject(PageHelpService);
  private readonly store = inject(GalleryStore);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly toolbarTpl = viewChild<TemplateRef<unknown>>('foldersToolbar');

  protected readonly folders = signal<FolderItem[]>([]);
  protected readonly loading = signal(false);
  protected readonly currentPrefix = signal('');

  protected readonly breadcrumbs = computed(() => buildFolderBreadcrumbs(this.currentPrefix()));

  constructor() {
    // Re-fetch on prefix navigation AND whenever the gallery's effective hide
    // toggles change — deep-linking to /folders can race loadConfig() (it's
    // fired without awaiting), so reading the store signal here is what makes
    // the counts self-heal once config lands.
    effect(() => {
      this.currentPrefix();
      this.store.viewFilterParams();
      this.loadFolders();
    });
    effect(() => {
      const t = this.toolbarTpl();
      if (t) this.headerSlot.set(t);
    });
  }

  ngOnDestroy(): void {
    const t = this.toolbarTpl();
    if (t) this.headerSlot.clear(t);
  }

  ngOnInit(): void {
    this.pageHelp.setDescription(I18N.folders.help);
    this.destroyRef.onDestroy(() => this.pageHelp.setDescription(null));
    this.route.queryParams.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      this.currentPrefix.set(params['prefix'] || '');
    });
  }

  private loadSeq = 0;

  private async loadFolders(): Promise<void> {
    const seq = ++this.loadSeq;
    this.loading.set(true);
    // A redirect branch leaves loading true: the navigation re-runs this load for the next
    // prefix, and clearing it here would flash the empty state between hops.
    let redirected = false;
    try {
      const res = await firstValueFrom(
        this.api.get<FoldersResponse>('/folders', {
          prefix: this.currentPrefix(),
          ...this.store.viewFilterParams(),
        }),
      );
      // A newer load owns the spinner and the list; a late answer must not redirect or overwrite it.
      if (seq !== this.loadSeq) { redirected = true; return; }
      // Auto-redirect to gallery if no subfolders (leaf directory)
      // replaceUrl avoids a back-button loop (back → leaf folder → redirect → gallery → …)
      if (res.folders.length === 0 && this.currentPrefix()) {
        redirected = true;
        this.settleRedirect(this.router.navigate(['/'], {
          queryParams: {
            path_prefix: this.currentPrefix(),
            sort: 'date_taken',
            sort_direction: 'DESC',
          },
          replaceUrl: true,
        }));
        return;
      }
      // A lone folder with nothing beside it is a path prefix, not a choice (/Users/me/...).
      // Skip to the first level that branches; the breadcrumb still shows the chain.
      // Not when a breadcrumb led here: that level was chosen, and skipping bounced straight back.
      if (res.folders.length === 1 && !res.has_direct_photos && !history.state?.[KEEP_CHAIN_STATE]) {
        redirected = true;
        this.settleRedirect(this.router.navigate(['/folders'], { queryParams: { prefix: res.folders[0].path }, replaceUrl: true }));
        return;
      }
      this.folders.set(res.folders);
    } finally {
      if (!redirected) this.loading.set(false);
    }
  }

  /** A redirect that does not happen (resolved false or rejected) must not leave the spinner up for good. */
  private settleRedirect(navigation: Promise<boolean>): void {
    Promise.resolve(navigation).then(
      navigated => { if (!navigated) this.loading.set(false); },
      () => this.loading.set(false),
    );
  }

  protected navigateTo(prefix: string): void {
    this.router.navigate(['/folders'], {
      queryParams: prefix ? { prefix } : {},
      state: { [KEEP_CHAIN_STATE]: true },
    });
  }

  protected openFolder(folder: FolderItem): void {
    this.router.navigate(['/folders'], {
      queryParams: { prefix: folder.path },
    });
  }

  protected filterInGallery(folder: FolderItem): void {
    this.router.navigate(['/'], {
      queryParams: {
        path_prefix: folder.path,
        sort: 'date_taken',
        sort_direction: 'DESC',
      },
    });
  }
}
