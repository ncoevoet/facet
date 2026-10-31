import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal, ElementRef, Injector, afterNextRender, viewChildren } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { i18nKeys } from '../../core/i18n/keys';
import { Photo } from '../../shared/models/photo.model';
import { ThumbnailUrlPipe, ImageUrlPipe, STORED_THUMBNAIL_EDGE, RENDERED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SyncedZoomComponent, ZoomState, FIT_ZOOM, MAX_COMPARE_PANES } from './synced-zoom.component';

// Module-level consts, not direct class-field initializers: Vite's test transform
// snapshots an imported binding used as a field initializer before a
// lazily-initialised shared chunk sets it.
const STORED_EDGE = STORED_THUMBNAIL_EDGE;
const RENDERED_EDGE = RENDERED_THUMBNAIL_EDGE;

export interface CompareSelectedData {
  photos: Photo[];
}

/**
 * Side-by-side pixel-peeking over a hand-picked gallery selection.
 *
 * The culling lightbox already compares frames this way, but only ever the ones
 * sitting next to each other in a burst. Deciding between two shots of the same
 * subject taken minutes apart -- or from different folders entirely -- had no
 * surface at all. This reuses `SyncedZoomComponent` wholesale, including its
 * swap to a full-resolution source past the fit scale, so both places pan and
 * zoom identically rather than growing two implementations of the same gesture.
 */
@Component({
  selector: 'app-compare-selected-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatDialogModule, MatIconModule, MatButtonModule, MatTooltipModule,
    SyncedZoomComponent, ThumbnailUrlPipe, ImageUrlPipe, TranslatePipe,
  ],
  template: `
    <div class="flex flex-col h-full bg-[var(--mat-sys-surface)] text-[var(--mat-sys-on-surface)]">
      <div class="flex flex-wrap items-center gap-2 border-b border-[var(--mat-sys-outline-variant)] px-3 py-2 text-sm shrink-0">
        <mat-icon class="!text-base !w-5 !h-5 !leading-5">compare</mat-icon>
        <span class="flex-1 truncate">{{ I18N.gallery.compare.title | translate:{ count: panes().length } }}</span>
        @if (panes().length > 2) {
          <button mat-button data-two-up class="!text-[var(--mat-sys-on-surface)] shrink-0" [attr.aria-pressed]="twoUp()"
                  [attr.aria-label]="I18N.gallery.compare.two_up | translate" (click)="twoUp.set(!twoUp())">
            <mat-icon>view_column_2</mat-icon><span class="hidden sm:inline">{{ I18N.gallery.compare.two_up | translate }}</span>
          </button>
        }
        <button mat-button data-link-inspection class="!text-[var(--mat-sys-on-surface)] shrink-0"
                [attr.aria-pressed]="linked()"
                [attr.aria-label]="(linked() ? I18N.gallery.compare.linked : I18N.gallery.compare.independent) | translate"
                [matTooltip]="I18N.gallery.compare.link_help | translate"
                (click)="toggleLinked()">
          <mat-icon>{{ linked() ? 'link' : 'link_off' }}</mat-icon>
          <span class="hidden sm:inline">{{ (linked() ? I18N.gallery.compare.linked : I18N.gallery.compare.independent) | translate }}</span>
        </button>
        @if (zoomed()) {
          <button mat-icon-button class="!text-[var(--mat-sys-on-surface)]"
                  [matTooltip]="I18N.gallery.compare.reset_zoom | translate"
                  [attr.aria-label]="I18N.gallery.compare.reset_zoom | translate"
                  (click)="resetZoom()">
            <mat-icon>zoom_out_map</mat-icon>
          </button>
        }
        <button mat-icon-button class="!text-[var(--mat-sys-on-surface)]"
                [matTooltip]="I18N.dialog.close | translate"
                [attr.aria-label]="I18N.dialog.close | translate"
                (click)="close()">
          <mat-icon>close</mat-icon>
        </button>
      </div>

      <div class="flex-1 min-h-0 grid grid-cols-1 sm:grid-cols-2 gap-2 p-2 bg-neutral-950"
           [class.!grid-cols-1]="visiblePhotos().length < 2"
           [class.!grid-cols-2]="visiblePhotos().length > 2"
           [class.max-sm:grid-rows-2]="visiblePhotos().length === 2"
           [class.grid-rows-2]="visiblePhotos().length > 2">
        @for (pane of paneStates(); track pane.photo.path) {
          @let photo = pane.photo;
          <div class="relative flex flex-col w-full h-full min-h-0 overflow-hidden border border-neutral-700" [class.border-[var(--mat-sys-primary)]]="activePath() === photo.path" [attr.data-reference]="referencePath() === photo.path" [attr.data-active-pane]="activePath() === photo.path" (pointerdown)="activate(photo.path)" (focusin)="activate(photo.path)">
            <div class="flex items-center gap-2 px-2 py-1 text-white text-xs bg-neutral-900 min-h-10">
              <mat-icon class="!text-base !w-4 !h-4 shrink-0">{{ referencePath() === photo.path ? 'push_pin' : 'photo' }}</mat-icon>
              <span class="shrink-0">{{ (referencePath() === photo.path ? I18N.gallery.compare.reference : I18N.gallery.compare.candidate) | translate }}</span>
              <span class="truncate min-w-0 flex-1">{{ photo.filename }}</span>
              @if (referencePath() !== photo.path) {
                <button mat-icon-button data-promote-reference class="!text-white shrink-0"
                        [attr.aria-label]="I18N.gallery.compare.promote | translate:{ name: photo.filename }"
                        [matTooltip]="I18N.gallery.compare.promote | translate:{ name: photo.filename }"
                        (click)="promote(photo.path)"><mat-icon>push_pin</mat-icon></button>
              }
              <button mat-icon-button data-remove-pane class="!text-white shrink-0" [disabled]="panes().length < 2"
                      [attr.aria-label]="I18N.gallery.compare.remove_pane | translate:{ name: photo.filename }"
                      [matTooltip]="I18N.gallery.compare.remove_pane | translate:{ name: photo.filename }"
                      (click)="removePane(photo.path)"><mat-icon>close</mat-icon></button>
            </div>
            <app-synced-zoom class="w-full h-full min-h-0"
                             [src]="photo.path | thumbnailUrl:renderedEdge:photo.preview_revision"
                             [placeholderSrc]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision"
                             [frameKey]="photo.path"
                             [fullResSrc]="photo.path | imageUrl:true:photo.preview_revision"
                             [zoom]="pane.zoom"
                             (zoomChange)="onZoom(photo.path, $event)"
                             (sharpPending)="setReadiness(photo.path, 'loading')"
                             (sharpLoaded)="setReadiness(photo.path, 'ready')"
                             (sharpFailed)="setReadiness(photo.path, 'failed')"
                             [alt]="photo.filename" />
            <div data-preview-status class="absolute bottom-1 left-1 right-1 px-2 py-1 rounded bg-black/75 text-white text-xs truncate">
              {{ pane.statusKey | translate }}
            </div>
          </div>
        }
      </div>

      @if (twoUp() && candidates().length) {
        <div class="flex items-center justify-center gap-2 px-3 shrink-0 border-t border-[var(--mat-sys-outline-variant)]">
          <button mat-icon-button data-candidate-previous class="!text-[var(--mat-sys-on-surface)] disabled:!text-[var(--mat-sys-outline)]"
                  [disabled]="candidateIndex() <= 0" [attr.aria-label]="I18N.gallery.compare.previous_candidate | translate"
                  (click)="moveCandidate(-1)"><mat-icon>chevron_left</mat-icon></button>
          <span class="min-w-0 truncate text-xs" aria-live="polite">{{ I18N.gallery.compare.candidate_position | translate:{ current: candidateIndex() + 1, total: candidates().length } }}</span>
          <button mat-icon-button data-candidate-next class="!text-[var(--mat-sys-on-surface)] disabled:!text-[var(--mat-sys-outline)]"
                  [disabled]="candidateIndex() >= candidates().length - 1" [attr.aria-label]="I18N.gallery.compare.next_candidate | translate"
                  (click)="moveCandidate(1)"><mat-icon>chevron_right</mat-icon></button>
        </div>
      }
      <div class="shrink-0 border-t border-[var(--mat-sys-outline-variant)] px-3 py-2">
        <div class="flex items-center justify-between gap-2 mb-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
          <span>{{ I18N.gallery.compare.queue | translate:{ count: candidates().length } }}</span>
          @if (removedPaths().size) {
            <button mat-button data-restore-comparison (click)="restorePanes()">{{ I18N.gallery.compare.restore | translate }}</button>
          }
        </div>
        <div class="flex gap-2 overflow-x-auto" role="group" [attr.aria-label]="I18N.gallery.compare.queue_label | translate">
          @for (photo of panes(); track photo.path) {
            <button #candidateButton type="button" data-candidate-thumbnail [attr.data-path]="photo.path"
                    class="flex w-24 shrink-0 flex-col gap-1 rounded-md border border-[var(--mat-sys-outline-variant)] p-1 text-left focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
                    [class.bg-[var(--mat-sys-secondary-container)]]="activePath() === photo.path"
                    [attr.aria-pressed]="activePath() === photo.path"
                    [attr.aria-label]="((referencePath() === photo.path ? I18N.gallery.compare.reference : I18N.gallery.compare.candidate) | translate) + ': ' + photo.filename"
                    (click)="chooseCandidate(photo.path)">
              <img [src]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision" alt="" class="h-12 w-full object-contain bg-neutral-950" />
              <span class="flex items-center gap-1 text-xs w-full"><mat-icon class="!text-sm !w-4 !h-4 shrink-0">{{ referencePath() === photo.path ? 'push_pin' : 'photo' }}</mat-icon><span class="truncate">{{ photo.filename }}</span></span>
            </button>
          }
        </div>
      </div>
      <div class="px-3 pb-2 text-center text-[var(--mat-sys-on-surface-variant)] text-xs shrink-0">
        {{ I18N.gallery.compare.hint | translate }}
      </div>
    </div>
  `,
  host: { class: 'block h-full' },
})
export class CompareSelectedDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly dialogRef = inject(MatDialogRef<CompareSelectedDialogComponent>);
  private readonly data = inject<CompareSelectedData>(MAT_DIALOG_DATA);
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);
  private readonly candidateButtons = viewChildren<ElementRef<HTMLButtonElement>>('candidateButton');

  protected readonly storedEdge = STORED_EDGE;
  protected readonly renderedEdge = RENDERED_EDGE;

  /** Pan/zoom shared by every pane, so a gesture on one moves them all in lockstep. */
  protected readonly zoom = signal<ZoomState>({ ...FIT_ZOOM });
  protected readonly linked = signal(true);
  protected readonly referencePath = signal(this.data.photos?.[0]?.path ?? null);
  protected readonly twoUp = signal(false);
  protected readonly activePath = signal(this.data.photos?.[0]?.path ?? null);
  protected readonly removedPaths = signal(new Set<string>());
  private readonly candidatePath = signal(this.data.photos?.[1]?.path ?? null);
  private readonly independentZoom = signal(new Map<string, ZoomState>());
  private readonly readiness = signal(new Map<string, 'loading' | 'ready' | 'failed'>());

  /** Extra selected photos are dropped rather than shrunk past usefulness. */
  protected readonly panes = computed(() => (this.data.photos ?? []).slice(0, MAX_COMPARE_PANES).filter(photo => !this.removedPaths().has(photo.path)));
  protected readonly candidates = computed(() => this.panes().filter(photo => photo.path !== this.referencePath()));
  protected readonly candidateIndex = computed(() => Math.max(0, this.candidates().findIndex(photo => photo.path === this.candidatePath())));
  protected readonly visiblePhotos = computed(() => {
    if (!this.twoUp()) return this.panes();
    const reference = this.panes().find(photo => photo.path === this.referencePath());
    const candidate = this.candidates()[this.candidateIndex()];
    return [reference, candidate].filter((photo): photo is Photo => !!photo);
  });

  protected readonly paneStates = computed(() => this.visiblePhotos().map(photo => ({
    photo,
    zoom: this.linked() ? this.zoom() : this.independentZoom().get(photo.path) ?? this.zoom(),
    statusKey: { loading: this.I18N.gallery.compare.preview_loading, ready: this.I18N.gallery.compare.preview_ready, failed: this.I18N.gallery.compare.preview_failed }[this.readiness().get(photo.path) ?? 'loading'],
  })));

  protected readonly zoomed = computed(() => this.paneStates().some(pane => pane.zoom.scale > FIT_ZOOM.scale));

  protected promote(path: string): void {
    if (!this.panes().some(photo => photo.path === path)) return;
    const previous = this.referencePath();
    this.referencePath.set(path);
    this.candidatePath.set(previous);
    this.activePath.set(path);
  }

  protected moveCandidate(direction: number): void {
    const next = this.candidates()[this.candidateIndex() + direction];
    if (next) { this.candidatePath.set(next.path); this.activePath.set(next.path); }
  }

  protected activate(path: string): void {
    if (this.panes().some(photo => photo.path === path)) this.activePath.set(path);
  }

  protected chooseCandidate(path: string): void {
    if (!this.panes().some(photo => photo.path === path)) return;
    this.activePath.set(path);
    if (path !== this.referencePath()) {
      this.candidatePath.set(path);
      this.twoUp.set(true);
    }
  }

  /** Membership here is presentation state; the gallery selection and decisions never change. */
  protected removePane(path: string): void {
    const current = this.panes();
    if (current.length < 2 || !current.some(photo => photo.path === path)) return;
    const focusBefore = this.document.activeElement;
    const nextCandidates = this.candidates().filter(photo => photo.path !== path);
    const candidateIndex = this.candidateIndex();
    this.removedPaths.update(paths => new Set(paths).add(path));
    if (path === this.referencePath()) this.referencePath.set(this.panes()[0].path);
    if (path === this.candidatePath() || this.candidatePath() === this.referencePath()) {
      const available = nextCandidates.filter(photo => photo.path !== this.referencePath());
      this.candidatePath.set(available[Math.min(candidateIndex, available.length - 1)]?.path ?? null);
    }
    if (path === this.activePath()) this.activePath.set(this.candidatePath() ?? this.referencePath());
    this.independentZoom.update(values => { const next = new Map(values); next.delete(path); return next; });
    this.readiness.update(values => { const next = new Map(values); next.delete(path); return next; });
    afterNextRender(() => {
      if (this.document.activeElement !== this.document.body && this.document.activeElement !== focusBefore) return;
      this.candidateButtons().find(button => button.nativeElement.dataset['path'] === this.activePath())?.nativeElement.focus();
    }, { injector: this.injector });
  }

  protected restorePanes(): void {
    this.removedPaths.set(new Set());
  }

  protected onZoom(path: string, state: ZoomState): void {
    if (!this.panes().some(photo => photo.path === path)) return;
    if (this.linked()) this.zoom.set(state);
    else this.independentZoom.update(values => new Map(values).set(path, state));
  }

  protected toggleLinked(): void {
    if (this.linked()) {
      this.independentZoom.set(new Map(this.panes().map(photo => [photo.path, { ...this.zoom() }])));
      this.linked.set(false);
    } else {
      this.resetZoom();
      this.linked.set(true);
    }
  }

  protected setReadiness(path: string, state: 'loading' | 'ready' | 'failed'): void {
    if (!this.panes().some(photo => photo.path === path)) return;
    this.readiness.update(values => new Map(values).set(path, state));
  }

  protected resetZoom(): void {
    this.zoom.set({ ...FIT_ZOOM });
    this.independentZoom.set(new Map());
  }

  protected close(): void {
    this.dialogRef.close();
  }
}
