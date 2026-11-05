import { Component, ElementRef, Injector, afterNextRender, inject, signal, effect, viewChild, TemplateRef, OnInit, OnDestroy, HostListener, ChangeDetectionStrategy, untracked } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { isImeOrRepeat, isPageShortcutBlocked } from '../../shared/utils/keyboard';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { JunkKindLabelPipe, JunkKindIconPipe } from './junk-sweep.pipes';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { chunkPhotoPaths, type PhotosResponse } from '../gallery/gallery.store';
import { normalisePhotoFlagsAll, type Photo } from '../../shared/models/photo.model';
import { onPageQuery } from '../../shared/utils/page-query';

const ANY_KIND = 'any';

interface QueueView {
  generation: number;
  navigation: number;
  identity: string;
  kind: string;
}

@Component({
  selector: 'app-junk-sweep',
  host: { class: 'block h-full overflow-y-auto' },
  imports: [
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatTooltipModule,
    TranslatePipe,
    PluralKeyPipe,
    ThumbnailUrlPipe,
    ImageUrlPipe,
    LoupeDirective,
    JunkKindLabelPipe,
    JunkKindIconPipe,
    FilenamePipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <!-- The toolbar projects into the global header on lg+ (HeaderSlotService) and
         renders as a fixed bottom bar on small screens (same #junkToolbar template):
         filter group on the left, action group (loupe + reject-all) on the right. -->
    <div class="lg:hidden">
      <ng-container [ngTemplateOutlet]="junkToolbar" />
    </div>
    <ng-template #junkToolbar>
      <div class="flex items-center gap-2 md:gap-3
                  max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-40
                  max-lg:flex-wrap max-lg:px-3 max-lg:py-2
                  max-lg:bg-[var(--mat-sys-surface-container)] max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)]
                  max-lg:shadow-lg">
        <button mat-stroked-button data-junk-kind-menu class="!h-11 !min-w-0 shrink-0" [matMenuTriggerFor]="kindMenu" [disabled]="bulkBusy() || loading()"
                [class.!text-[var(--mat-sys-primary)]]="activeKind() !== ANY_KIND"
                [matTooltip]="activeKind() === ANY_KIND ? (I18N.junk.all_kinds | translate) : (activeKind() | junkKindLabel)"
                [attr.aria-label]="activeKind() === ANY_KIND ? (I18N.junk.all_kinds | translate) : (activeKind() | junkKindLabel)">
          <mat-icon>{{ activeKind() | junkKindIcon }}</mat-icon>
          <span class="block max-w-24 truncate sm:max-w-40">{{ activeKind() === ANY_KIND ? (I18N.junk.all_kinds | translate) : (activeKind() | junkKindLabel) }}</span>
        </button>
        @if (!((loading() || loadFailed()) && photos().length === 0)) {
          <span data-junk-count class="min-w-0 flex-1 truncate text-sm text-[var(--mat-sys-on-surface-variant)]"
                role="status" aria-live="polite">
            {{ total() | pluralKey:I18N.junk.candidates:I18N.junk.candidates_plural | translate:{ count: total() } }}
          </span>
        }
        <mat-menu #kindMenu="matMenu">
          <button mat-menu-item (click)="selectKind(ANY_KIND)">
            <mat-icon>{{ ANY_KIND | junkKindIcon }}</mat-icon>
            <span [class.font-bold]="activeKind() === ANY_KIND">{{ I18N.junk.all_kinds | translate }}</span>
          </button>
          @for (k of kinds(); track k[0]) {
            <button mat-menu-item (click)="selectKind(k[0])">
              <mat-icon>{{ k[0] | junkKindIcon }}</mat-icon>
              <span [class.font-bold]="activeKind() === k[0]">{{ k[0] | junkKindLabel }}</span>
              <span class="ml-2 text-xs opacity-50">{{ k[1] }}</span>
            </button>
          }
        </mat-menu>
        <div class="flex items-center gap-2 md:gap-3 ml-auto max-lg:contents">
          <button mat-icon-button class="!h-11 !w-11 shrink-0" (click)="loupeActive.set(!loupeActive())"
                  [class.!text-[var(--mat-sys-primary)]]="loupeActive()"
                  [attr.aria-pressed]="loupeActive()"
                  [matTooltip]="I18N.scenes.loupe_hint | translate"
                  [attr.aria-label]="I18N.scenes.loupe | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
          </button>
          @if (loupeActive()) {
            <div class="flex items-center gap-2 max-lg:order-last max-lg:basis-full">
            <span class="whitespace-nowrap text-xs">{{ I18N.scenes.loupe | translate }} {{ loupeZoom() }}×</span>
            <mat-slider data-junk-loupe-slider class="!w-28 !min-w-0 max-lg:flex-1 max-lg:!mx-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.scenes.loupe | translate" />
            </mat-slider>
            </div>
          }
          @if (photos().length > 0) {
            <button mat-stroked-button class="!h-11 !min-w-0 shrink-0" color="warn" (click)="rejectAllShown()"
                    [disabled]="bulkBusy() || loading() || pendingPaths().size > 0 || !auth.isEdition()"
                    [matTooltip]="I18N.junk.reject_all | translate:{ count: photos().length }"
                    [attr.aria-label]="I18N.junk.reject_all | translate:{ count: photos().length }">
              @if (bulkBusy()) {
                <mat-spinner diameter="18" [attr.aria-label]="I18N.ui.labels.loading | translate" />
              } @else {
                <mat-icon>block</mat-icon>
              }
              <span>{{ I18N.junk.reject_all | translate:{ count: photos().length } }}</span>
            </button>
          }
        </div>
      </div>
    </ng-template>

    <div #junkContent class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%] max-lg:pb-24" [class.max-lg:!pb-40]="loupeActive()">
      <h1 data-junk-heading tabindex="-1" class="mb-3 text-xl font-semibold">{{ I18N.nav.junk_sweep | translate }}</h1>
      @if (loading() && photos().length === 0) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" /></div>
      } @else if (photos().length === 0 && !loadFailed()) {
        <!-- A kind filter with no hits is not "no junk in the library": point
             back to All kinds instead of telling the user to rescan. -->
        <div class="text-[var(--mat-sys-on-surface-variant)] py-10 text-center whitespace-pre-line">{{ (activeKind() === ANY_KIND ? I18N.junk.empty : I18N.junk.empty_kind) | translate }}</div>
      } @else {
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          @for (photo of photos(); track photo.path) {
            <article data-junk-card class="min-w-0 overflow-hidden rounded-xl border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-lowest)]"
                     [attr.aria-busy]="pendingPaths().has(photo.path) || bulkBusy()">
              <div class="relative aspect-[4/3]">
                <img [src]="photo.path | thumbnailUrl:320:photo.preview_revision"
                     [appLoupe]="photo.path | imageUrl:true:photo.preview_revision"
                     [loupeActive]="loupeActive()"
                     [loupeZoom]="loupeZoom()"
                     class="w-full h-full object-cover"
                     [alt]="photo.filename" loading="lazy" />
                <span class="absolute top-1 left-1 bg-black/75 text-white text-[10px] px-1.5 py-0.5 rounded">
                  {{ photo.junk_kind | junkKindLabel }}
                </span>
              </div>
              <p class="min-w-0 px-2 pt-2 text-xs truncate" [title]="photo.filename">{{ photo.filename | filename:30 }}</p>
              <div class="grid grid-cols-2 gap-1 p-1">
                <button type="button" data-junk-keep
                        class="min-h-11 min-w-0 inline-flex flex-col sm:flex-row items-center justify-center gap-0.5 px-1 rounded-lg text-xs text-[var(--mat-sys-primary)] hover:bg-[var(--mat-sys-primary-container)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--mat-sys-primary)] disabled:opacity-50 disabled:cursor-default cursor-pointer"
                        [disabled]="bulkBusy() || loading() || pendingPaths().has(photo.path) || !auth.isEdition()"
                        [matTooltip]="I18N.junk.keep_hint | translate"
                        [attr.aria-label]="(I18N.junk.keep | translate) + ': ' + photo.filename"
                        (click)="keep(photo)">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0" aria-hidden="true">check</mat-icon>
                  <span>{{ I18N.junk.keep | translate }}</span>
                </button>
                <button type="button" data-junk-reject
                        class="min-h-11 min-w-0 inline-flex flex-col sm:flex-row items-center justify-center gap-0.5 px-1 rounded-lg text-xs text-[var(--mat-sys-error)] hover:bg-[var(--mat-sys-error-container)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--mat-sys-primary)] disabled:opacity-50 disabled:cursor-default cursor-pointer"
                        [disabled]="bulkBusy() || loading() || pendingPaths().has(photo.path) || !auth.isEdition()"
                        [matTooltip]="I18N.junk.reject_hint | translate"
                        [attr.aria-label]="(I18N.junk.reject | translate) + ': ' + photo.filename"
                        (click)="reject(photo)">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4 shrink-0" aria-hidden="true">block</mat-icon>
                  <span>{{ I18N.junk.reject | translate }}</span>
                </button>
              </div>
            </article>
          }
        </div>
        @if (hasMore() && !loadFailed()) {
          <div class="flex justify-center py-4">
            <button mat-stroked-button class="!min-h-11" (click)="loadMore()" [disabled]="loading() || bulkBusy() || pendingPaths().size > 0">{{ I18N.junk.load_more | translate }}</button>
          </div>
        }
      }
      @if (loadFailed()) {
        <div data-junk-load-error class="flex flex-wrap items-center justify-center gap-3 py-6" role="alert">
          <p class="text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.junk.load_error | translate }}</p>
          <button mat-stroked-button class="!min-h-11" data-junk-retry (click)="retryLoad()"
                  [disabled]="loading() || bulkBusy() || pendingPaths().size > 0">{{ I18N.gallery.load_error.retry | translate }}</button>
        </div>
      }
    </div>
  `,
})
export class JunkSweepComponent implements OnInit, OnDestroy {
  protected readonly I18N = i18nKeys();
  protected readonly ANY_KIND = ANY_KIND;
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly journal = inject(UserActivityJournal);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly router = inject(Router);
  private readonly element = viewChild<ElementRef<HTMLElement>>('junkContent');
  private readonly injector = inject(Injector);

  private readonly junkToolbar = viewChild<TemplateRef<unknown>>('junkToolbar');

  constructor() {
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.navigationGeneration++;
        this.pendingNavigation = event.id;
        this.loadGeneration++;
        this.loading.set(true);
      } else if ((event instanceof NavigationEnd || event instanceof NavigationCancel
          || event instanceof NavigationError || event instanceof NavigationSkipped) && event.id === this.pendingNavigation) {
        this.pendingNavigation = null;
        const navigation = this.navigationGeneration;
        const generation = this.viewGeneration;
        // A cancelled/redirected navigation does not resume the old write loop.
        // If this page survives, recover from a fresh authorized queue instead.
        queueMicrotask(() => {
          if (this.destroyed || this.pendingNavigation !== null || navigation !== this.navigationGeneration || generation !== this.viewGeneration
              || !this.initialized || !this.auth.isEdition() || this.router.url.split(/[?#]/)[0] !== '/junk') return;
          this.viewGeneration++;
          this.page = 0;
          this.bulkBusy.set(false);
          this.photos.set([]);
          this.total.set(0);
          this.hasMore.set(false);
          void this.loadKinds();
          void this.load(1);
        });
      }
    });
    effect(() => {
      const tpl = this.junkToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
    effect(() => {
      const accessKey = `${this.auth.identity()}|${this.auth.isEdition()}`;
      if (accessKey === this.accessKey) return;
      this.accessKey = accessKey;
      untracked(() => {
        this.viewGeneration++;
        this.viewIdentity = this.auth.identity();
        this.reconcileView = null;
        this.loadGeneration++;
        this.photos.set([]);
        this.kinds.set([]);
        this.total.set(0);
        this.hasMore.set(false);
        this.loadFailed.set(false);
        this.loading.set(false);
        this.bulkBusy.set(false);
        this.kindsLoaded = false;
        this.requestedKind = null;
        this.page = 0;
        if (this.initialized && !this.destroyed && this.auth.isEdition()) {
          void this.loadKinds();
          void this.load(1);
        }
      });
    });
    // The assistant's `junk_list show=true` sends the kind every time; it is applied once the kind list is known.
    onPageQuery('/junk', ['kind'], query => {
      this.requestedKind = query.get('kind');
      this.applyRequestedKind();
    });
  }

  protected readonly photos = signal<Photo[]>([]);
  protected readonly kinds = signal<[string, number][]>([]);
  protected readonly activeKind = signal<string>(ANY_KIND);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);

  private readonly loupe = createLoupeState();
  protected readonly loupeActive = this.loupe.loupeActive;
  protected readonly loupeZoom = this.loupe.loupeZoom;

  protected readonly loadFailed = signal(false);
  protected readonly bulkBusy = signal(false);
  protected readonly pendingPaths = signal<ReadonlySet<string>>(new Set());

  private page = 0;
  private failedPage = 1;
  private viewGeneration = 0;
  private navigationGeneration = 0;
  private pendingNavigation: number | null = null;
  private destroyed = false;
  private initialized = false;
  private viewIdentity = this.auth.identity();
  private reconcileView: QueueView | null = null;
  private accessKey = `${this.auth.identity()}|${this.auth.isEdition()}`;
  private readonly perPage = 48;
  private loadGeneration = 0;
  private requestedKind: string | null = null;
  private kindsLoaded = false;

  async ngOnInit(): Promise<void> {
    this.pageHelp.setDescription(I18N.junk.help);
    this.initialized = true;
    if (!this.auth.isEdition()) {
      this.loading.set(false);
      return;
    }
    void this.loadKinds();
    await this.load(1);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.viewGeneration++;
    this.loadGeneration++;
    this.pageHelp.setDescription(null);
    const tpl = this.junkToolbar();
    if (tpl) this.headerSlot.clear(tpl);
  }

  private async loadKinds(): Promise<void> {
    const view = this.captureView();
    try {
      const data = await firstValueFrom(
        this.api.get<{ junk_kinds: [string, number][] }>('/filter_options/junk_kinds'),
      );
      if (!this.isCurrentView(view)) return;
      this.kinds.set(data.junk_kinds ?? []);
    } catch {
      // The kind filter menu stays empty; the "All kinds" view still works.
    } finally {
      if (this.isCurrentView(view)) {
        this.kindsLoaded = true;
        this.applyRequestedKind();
      }
    }
  }

  /** Select the kind a navigation asked for, once the kind list can say whether it exists. */
  private applyRequestedKind(): void {
    const kind = this.requestedKind;
    if (kind === null || !this.kindsLoaded || this.pendingNavigation !== null) return;
    this.requestedKind = null;
    if (kind === ANY_KIND || this.kinds().some(entry => entry[0] === kind)) void this.selectKind(kind);
  }

  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    if (!(event instanceof KeyboardEvent) || isPageShortcutBlocked(event) || isImeOrRepeat(event)) return;
    this.loupe.toggle(event);
  }

  protected async selectKind(kind: string): Promise<void> {
    if (this.destroyed || this.pendingNavigation !== null || this.bulkBusy() || kind === this.activeKind() || !this.auth.isEdition()) return;
    this.viewGeneration++;
    this.activeKind.set(kind);
    this.page = 0;
    this.photos.set([]);
    // The previous kind's total must not survive a failed first load of this one.
    this.total.set(0);
    this.hasMore.set(false);
    await this.load(1);
  }

  private captureView(): QueueView {
    return { generation: this.viewGeneration, navigation: this.navigationGeneration, identity: this.viewIdentity, kind: this.activeKind() };
  }

  private isCurrentView(view: QueueView): boolean {
    return !this.destroyed && this.pendingNavigation === null && view.navigation === this.navigationGeneration
      && this.auth.isEdition() && view.generation === this.viewGeneration
      && view.identity === this.auth.identity() && view.identity === this.viewIdentity && view.kind === this.activeKind();
  }

  private async load(requestedPage: number): Promise<boolean> {
    const view = this.captureView();
    if (!this.isCurrentView(view)) return false;
    const gen = ++this.loadGeneration;
    this.loading.set(true);
    this.loadFailed.set(false);
    try {
      const data = await firstValueFrom(
        this.api.get<PhotosResponse>('/photos', {
          type: '',
          junk_kind: view.kind,
          page: requestedPage,
          per_page: this.perPage,
          hide_rejected: 1,
          hide_blinks: 0,
          hide_bursts: 0,
          hide_duplicates: 0,
          collapse_stacks: 0,
        }),
      );
      if (gen !== this.loadGeneration || !this.isCurrentView(view)) return false;
      // A refill re-reads page 1, which can repeat a card restored after a failed write.
      this.photos.update(list => {
        const shown = new Set(list.map(p => p.path));
        return [...list, ...normalisePhotoFlagsAll(data.photos).filter(p => !shown.has(p.path))];
      });
      this.total.set(data.total);
      this.page = requestedPage;
      this.hasMore.set(requestedPage < data.total_pages);
      return true;
    } catch {
      if (gen !== this.loadGeneration || !this.isCurrentView(view)) return false;
      this.failedPage = requestedPage;
      this.loadFailed.set(true);
      return false;
    } finally {
      if (gen === this.loadGeneration && this.isCurrentView(view)) this.loading.set(false);
    }
  }

  protected async retryLoad(): Promise<void> {
    if (!this.loadFailed() || this.loading() || this.bulkBusy() || this.pendingPaths().size > 0) return;
    const active = document.activeElement as HTMLElement | null;
    const origin = active?.matches('[data-junk-retry]') ? active : null;
    const view = this.captureView();
    if (await this.load(this.failedPage)) this.restoreFocus(view, origin, 0);
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore() || this.loading() || this.bulkBusy() || this.pendingPaths().size > 0) return;
    const view = this.captureView();
    const shown = this.photos().length;
    // Decisions shrink this offset-paginated server queue. Re-read its boundary
    // page, deduplicate, then read at most one further page to make useful progress.
    // This recovers shifted candidates without replaying every loaded page.
    const boundaryPage = Math.floor(shown / this.perPage) + 1;
    if (!await this.load(boundaryPage) || !this.isCurrentView(view)) return;
    if (this.hasMore() && this.photos().length - shown < this.perPage) await this.load(this.page + 1);
  }

  /** Keep is a durable not_junk correction, not a Keep review decision. */
  protected async keep(photo: Photo): Promise<void> {
    await this.decide(photo, false);
  }

  /** Reject changes the review decision; no file is deleted. */
  protected async reject(photo: Photo): Promise<void> {
    await this.decide(photo, true);
  }

  private async decide(photo: Photo, reject: boolean): Promise<void> {
    const view = this.captureView();
    if (!this.isCurrentView(view) || this.bulkBusy() || this.loading() || this.pendingPaths().has(photo.path)
        || !this.photos().some(candidate => candidate.path === photo.path)) return;
    const origin = document.activeElement as HTMLElement | null;
    const ownedFocus = !!origin?.closest('[data-junk-card]');
    const index = this.photos().findIndex(candidate => candidate.path === photo.path);
    this.pendingPaths.update(paths => new Set([...paths, photo.path]));
    this.removeLocal(photo);
    if (ownedFocus) this.restoreFocus(view, origin, index);
    try {
      if (reject) {
        await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: [photo.path] }));
      } else {
        await firstValueFrom(this.api.post('/photo/clear_junk', { photo_path: photo.path }));
      }
      if (!this.isCurrentView(view)) return;
      this.journal.record('junk', [photo.path], { action: reject ? 'reject' : 'clear', count: 1 });
      this.notify(reject ? I18N.junk.rejected : I18N.junk.kept, 1500);
    } catch {
      if (!this.isCurrentView(view)) return;
      this.restoreLocal(photo);
      this.notifyDecisionError();
    } finally {
      const current = this.captureView();
      // A kind change can occur while a decision is pending. A matching new
      // view needs a fresh queue read, never an old view's optimistic rollback.
      if (!this.isCurrentView(view) && this.isCurrentView(current) && current.identity === view.identity
          && (current.kind === ANY_KIND || current.kind === photo.junk_kind)) this.reconcileView = current;
      this.pendingPaths.update(paths => {
        const remaining = new Set(paths);
        remaining.delete(photo.path);
        return remaining;
      });
      const reconciliation = this.reconcileView;
      if (this.pendingPaths().size === 0 && reconciliation && this.isCurrentView(reconciliation)) {
        this.reconcileView = null;
        this.page = 0;
        this.photos.set([]);
        await this.load(1);
      } else if (this.isCurrentView(view)) await this.refillIfDrained();
    }
  }

  protected async rejectAllShown(): Promise<void> {
    const view = this.captureView();
    if (!this.isCurrentView(view) || this.bulkBusy() || this.loading() || this.pendingPaths().size > 0) return;
    const shown = this.photos();
    if (shown.length === 0) return;
    this.bulkBusy.set(true);
    const rejected: string[] = [];
    try {
      const ref = this.dialog.open(ConfirmDialogComponent, {
        data: {
          title: this.i18n.t(I18N.junk.confirm_reject_all_title),
          message: this.i18n.t(I18N.junk.confirm_reject_all_message, { count: shown.length }),
        },
      });
      const confirmed = await firstValueFrom(ref.afterClosed());
      if (!confirmed || !this.isCurrentView(view)) return;
      // Only the loaded, confirmed snapshot is sent, never a library-wide filter.
      for (const chunk of chunkPhotoPaths(shown.map(photo => photo.path))) {
        if (!this.isCurrentView(view)) return;
        await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: chunk }));
        if (!this.isCurrentView(view)) return;
        rejected.push(...chunk);
      }
      this.journal.record('junk', rejected, { action: 'reject', count: rejected.length });
      this.notify(I18N.junk.rejected_bulk, 2000, { count: rejected.length });
      const removedByKind = new Map<string, number>();
      for (const photo of shown) {
        if (photo.junk_kind) removedByKind.set(photo.junk_kind, (removedByKind.get(photo.junk_kind) ?? 0) + 1);
      }
      this.kinds.update(list => list.map(kind => [kind[0], Math.max(0, kind[1] - (removedByKind.get(kind[0]) ?? 0))] as [string, number]));
      this.page = 0;
      this.photos.set([]);
      await this.load(1);
    } catch {
      if (!this.isCurrentView(view)) return;
      if (rejected.length > 0) {
        this.journal.record('junk', rejected, { action: 'reject', count: rejected.length, partial: true });
      }
      this.notifyDecisionError();
      // Re-read after a failed bulk write, including when earlier chunks landed.
      this.page = 0;
      this.photos.set([]);
      await this.load(1);
    } finally {
      if (this.isCurrentView(view)) this.bulkBusy.set(false);
    }
  }

  /** Wait until all pending writes have settled before refilling a drained queue. */
  private async refillIfDrained(): Promise<void> {
    if (this.pendingPaths().size > 0 || this.photos().length > 0 || !this.hasMore() || this.loading()) return;
    this.page = 0;
    await this.load(1);
  }

  private notify(key: string, duration: number, vars?: Record<string, string | number>): void {
    this.snack.open(this.i18n.t(key, vars), this.i18n.t(I18N.common.dismiss), { duration });
  }

  private notifyDecisionError(): void {
    this.notify(I18N.junk.decision_error, 3000);
  }

  private restoreFocus(view: QueueView, origin: HTMLElement | null, index: number): void {
    if (!origin) return;
    afterNextRender(() => {
      if (!this.isCurrentView(view) || (document.activeElement !== document.body && document.activeElement !== origin)) return;
      const root = this.element()?.nativeElement;
      const buttons = root?.querySelectorAll<HTMLElement>('[data-junk-keep]:not([disabled])');
      (buttons?.[Math.min(index, buttons.length - 1)] ?? root?.querySelector<HTMLElement>('[data-junk-heading]'))?.focus();
    }, { injector: this.injector });
  }

  private removeLocal(photo: Photo): void {
    this.photos.update(list => list.filter(p => p.path !== photo.path));
    this.total.update(t => Math.max(0, t - 1));
    if (photo.junk_kind) {
      this.kinds.update(list =>
        list.map(k => (k[0] === photo.junk_kind ? [k[0], Math.max(0, k[1] - 1)] as [string, number] : k)));
    }
  }

  private restoreLocal(photo: Photo): void {
    // A load since the removal may have listed it again, and its total already counts it.
    if (this.photos().some(p => p.path === photo.path)) return;
    this.photos.update(list => [photo, ...list]);
    this.total.update(t => t + 1);
    if (photo.junk_kind) {
      this.kinds.update(list =>
        list.map(k => (k[0] === photo.junk_kind ? [k[0], k[1] + 1] as [string, number] : k)));
    }
  }
}
