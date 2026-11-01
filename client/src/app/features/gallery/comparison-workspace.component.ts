import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, ElementRef, Injector, DestroyRef, afterNextRender, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import { NavigationCancel, NavigationError, Router } from '@angular/router';
import { ComparisonSessionService } from './comparison-session.service';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { i18nKeys } from '../../core/i18n/keys';
import { Photo } from '../../shared/models/photo.model';
import { ThumbnailUrlPipe, ImageUrlPipe, STORED_THUMBNAIL_EDGE, RENDERED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SyncedZoomComponent, ZoomState, DisplayedRendition, FIT_ZOOM } from './synced-zoom.component';
import { MAX_COMPARE_PANES } from './comparison-slots.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import type { PhotoFaceRow } from '../photo-detail/photo-face-layer.component';
import { KEY_SUBJECT_COORDINATE_SPACE } from './burst-culling.pipes';
import type { KeySubject } from './burst-culling.pipes';
import { normalizedInspectionBox, sharedInspectionPeople, NormalizedBox } from './comparison-inspection.util';
import { isTypingContext } from '../../shared/utils/keyboard';
import { PhotoAssessmentComponent } from '../../shared/components/photo-assessment/photo-assessment.component';

// Module-level consts, not direct class-field initializers: Vite's test transform
// snapshots an imported binding used as a field initializer before a
// lazily-initialised shared chunk sets it.
const STORED_EDGE = STORED_THUMBNAIL_EDGE;
const RENDERED_EDGE = RENDERED_THUMBNAIL_EDGE;

/** A read-only light table over captured gallery membership, with per-frame inspection. */
@Component({
  selector: 'app-comparison-workspace',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PhotoAssessmentComponent,
    MatIconModule, MatButtonModule, MatTooltipModule,
    SyncedZoomComponent, ThumbnailUrlPipe, ImageUrlPipe, TranslatePipe,
  ],
  template: `
    <div data-comparison-workspace class="flex flex-col h-full min-h-0 bg-[var(--mat-sys-surface)] text-[var(--mat-sys-on-surface)]">
      <div class="flex flex-wrap items-center gap-2 border-b border-[var(--mat-sys-outline-variant)] px-3 py-2 text-sm shrink-0">
        <button mat-icon-button class="!text-[var(--mat-sys-on-surface)]"
                [matTooltip]="I18N.ui.buttons.back | translate"
                [attr.aria-label]="I18N.ui.buttons.back | translate"
                (click)="close()">
          <mat-icon>arrow_back</mat-icon>
        </button>
        <mat-icon class="!text-base !w-5 !h-5 !leading-5">compare</mat-icon>
        <h1 class="m-0 flex-1 truncate text-sm font-semibold">{{ I18N.gallery.compare.title | translate:{ count: visiblePhotos().length } }}</h1>
        <button mat-button data-inspection-toggle class="!text-[var(--mat-sys-on-surface)] shrink-0" [attr.aria-expanded]="inspectionOpen()" aria-controls="comparison-inspection" [attr.aria-label]="I18N.gallery.compare.inspection.title | translate" (click)="toggleInspection()"><mat-icon>manage_search</mat-icon><span class="hidden sm:inline">{{ I18N.gallery.compare.inspection.title | translate }}</span></button>
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

      </div>

      <span id="comparison-inspection-help" class="sr-only">{{ I18N.gallery.compare.inspection.keyboard | translate }}</span>

      <div class="relative flex flex-1 min-h-0 min-w-0">
      <div data-comparison-canvas class="flex-1 min-w-0 min-h-0 grid grid-cols-1 sm:grid-cols-2 gap-1 p-1 bg-[var(--facet-image-canvas)]"
           [class.!grid-cols-1]="visiblePhotos().length < 2"
           [class.!grid-cols-2]="visiblePhotos().length > 2"
           [class.max-sm:grid-rows-2]="visiblePhotos().length === 2"
           [class.grid-rows-2]="visiblePhotos().length > 2">
        @for (pane of paneStates(); track pane.photo.path) {
          @let photo = pane.photo;
          <div class="@container/pane relative flex flex-col w-full h-full min-h-0 overflow-hidden border border-[var(--facet-image-rule)]" [class.border-[var(--mat-sys-primary)]]="activePath() === photo.path" [attr.data-reference]="referencePath() === photo.path" [attr.data-active-pane]="activePath() === photo.path" (pointerdown)="activate(photo.path)" (focusin)="activate(photo.path)">
            <div class="flex shrink-0 items-center gap-2 px-2 text-[var(--facet-image-ink)] text-xs bg-[var(--facet-image-chrome)] min-h-10">
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
            <app-synced-zoom #imagePane class="w-full flex-1 min-h-0"
                             [src]="photo.path | thumbnailUrl:renderedEdge:photo.preview_revision"
                             [placeholderSrc]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision"
                             [frameKey]="photo.path"
                             [fullResSrc]="photo.path | imageUrl:false:photo.preview_revision"
                             [zoom]="pane.zoom"
                             [keyboardInspection]="true"
                             aria-describedby="comparison-inspection-help"
                             [loupeActive]="loupe() && pane.zoom.scale === 1"
                             [loupeZoom]="loupeZoom()"
                             (zoomChange)="onZoom(photo.path, $event)"
                             (fitRequested)="fitPane(photo.path)"
                             (sharpPending)="setReadiness(photo.path, 'loading')"
                             (sharpLoaded)="setReadiness(photo.path, 'ready')"
                             (sharpFailed)="setReadiness(photo.path, 'failed')"
                             (renditionChange)="setRendition(photo.path, $event)"
                             [alt]="photo.filename" />
            <div class="shrink-0 flex flex-wrap items-center gap-x-1 border-t border-[var(--facet-image-rule)] bg-[var(--facet-image-chrome)] text-[var(--facet-image-ink)] px-2">
              <div class="flex w-full @[320px]/pane:w-auto @[320px]/pane:flex-1 min-w-0 items-center">
              <span data-preview-status role="status" class="min-w-0 flex-1 truncate text-xs" [title]="I18N.gallery.compare.rendition.limit | translate">
                {{ pane.kindKey | translate }} · {{ pane.phaseKey | translate }}
                @if (pane.rendition?.phase === 'ready') { {{ pane.rendition.width }} × {{ pane.rendition.height }} }
              </span>
              @if (pane.rendition?.phase === 'failed' || pane.previewFailed) {
                <button mat-icon-button data-retry-pane class="!text-white" [attr.aria-label]="I18N.gallery.load_error.retry | translate" (click)="imagePane.retry()"><mat-icon>refresh</mat-icon></button>
              }
              </div>
              <div class="flex w-full @[320px]/pane:w-auto min-w-0 items-center justify-center">
              <button mat-icon-button data-zoom-out class="!text-white" [disabled]="pane.zoomOutDisabled" [attr.aria-label]="I18N.gallery.compare.rendition.zoom_out | translate" (click)="stepZoom(photo.path, -1)"><mat-icon>remove</mat-icon></button>
              <button mat-button data-fit-pane class="!text-white !min-w-10 !px-1" [attr.aria-label]="I18N.gallery.compare.rendition.fit | translate" [matTooltip]="I18N.gallery.compare.rendition.scale_help | translate" (click)="fitPane(photo.path)">@if (pane.fitted) { {{ I18N.gallery.compare.rendition.fit_short | translate }} } @else { {{ pane.scaleLabel }} }</button>
              <button mat-icon-button data-zoom-in class="!text-white" [disabled]="pane.zoomInDisabled" [attr.aria-label]="I18N.gallery.compare.rendition.zoom_in | translate" (click)="stepZoom(photo.path, 1)"><mat-icon>add</mat-icon></button>
              </div>
            </div>
          </div>
        }
      </div>
      @if (inspectionOpen()) {
        <section id="comparison-inspection" class="absolute inset-x-0 bottom-0 z-10 max-h-[65%] overflow-y-auto border-t border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] p-3 text-xs sm:static sm:max-h-none sm:w-72 sm:shrink-0 sm:border-l sm:border-t-0" [attr.aria-label]="I18N.gallery.compare.inspection.title | translate">
          <div class="flex flex-wrap items-center gap-2">
            <button mat-button data-comparison-loupe [attr.aria-pressed]="loupe()" (click)="loupe.set(!loupe())"><mat-icon>search</mat-icon>{{ I18N.culling.loupe | translate }}</button>
            <label class="inline-flex items-center gap-1">{{ I18N.gallery.compare.inspection.magnification | translate }}<select class="rounded border bg-[var(--mat-sys-surface-container)] px-2 py-1" [value]="loupeZoom()" (change)="setLoupeZoom($event)"><option value="2">2×</option><option value="3">3×</option><option value="5">5×</option></select></label>
            @if (inspectionState() === 'loading') { <span role="status">{{ I18N.ui.labels.loading | translate }}</span> }
            @if (inspectionState() === 'partial') { <button mat-button data-inspection-retry (click)="loadInspection()">{{ I18N.gallery.load_error.retry | translate }}</button><span role="status">{{ I18N.gallery.compare.inspection.partial | translate }}</span> }
            <select data-shared-person [disabled]="!sharedPeople().length" [attr.aria-label]="I18N.gallery.compare.inspection.shared_person | translate" class="max-w-full rounded border bg-[var(--mat-sys-surface-container)] px-2 py-1" (change)="frameSharedPerson($event)">
              <option value="">{{ I18N.gallery.compare.inspection.shared_person | translate }}</option>
              @for (person of sharedPeople(); track person.id) { <option [value]="person.id">{{ person.name }}</option> }
            </select>
          </div>
          <p class="my-1">{{ I18N.gallery.compare.inspection.help | translate }}</p>
          <details><summary class="cursor-pointer py-1">{{ I18N.shortcuts.title | translate }}</summary><p class="my-1">{{ I18N.gallery.compare.inspection.keyboard | translate }}</p></details>
          @if (inspectionNotice()) { <p role="status" class="my-1">{{ inspectionNotice()! | translate }}</p> }
          @if (!sharedPeople().length && inspectionState() !== 'loading') { <p class="my-1">{{ I18N.gallery.compare.inspection.no_correspondence | translate }}</p> }
          <div class="grid gap-3">
            @for (pane of paneStates(); track pane.photo.path) {
              <div class="flex min-w-0 flex-wrap items-center gap-1">
                <span class="max-w-28 truncate" [title]="pane.photo.filename">{{ pane.photo.filename }}</span>
                <app-photo-assessment class="w-full" [photo]="pane.photo" />
                <button mat-button class="!text-xs" data-frame-suggestion [disabled]="!pane.suggestion" (click)="frameSuggestion(pane.photo.path)">{{ (pane.suggestion?.kind === 'person' ? I18N.gallery.compare.inspection.suggested_face : pane.suggestion?.kind === 'subject' ? I18N.gallery.compare.inspection.suggested_subject : inspectionState() === 'loading' ? I18N.ui.labels.loading : I18N.gallery.compare.inspection.no_crop) | translate }}</button>
                <select data-frame-face [disabled]="!pane.faces.length" [attr.aria-label]="(I18N.gallery.compare.inspection.choose_face | translate) + ': ' + pane.photo.filename" class="min-w-0 max-w-40 rounded border bg-[var(--mat-sys-surface-container)] px-1 py-1" (change)="frameFace(pane.photo.path, $event)">
                  <option value="">{{ I18N.gallery.compare.inspection.choose_face | translate }}</option>
                  @for (face of pane.faces; track face.id) { <option [value]="face.id">{{ face.person_name || (I18N.photo_faces.unknown | translate) }} · {{ face.face_index + 1 }}</option> }
                </select>
              </div>
            }
          </div>
      <div class="mt-3 text-xs text-[var(--mat-sys-on-surface-variant)]">
        {{ I18N.gallery.compare.hint | translate }}
        <details class="text-left"><summary class="cursor-pointer py-1">{{ I18N.gallery.compare.rendition.sources | translate }}</summary><p class="m-0">{{ I18N.gallery.compare.rendition.limit | translate }}</p><p class="m-0">{{ I18N.gallery.compare.rendition.scale_help | translate }}</p></details>
      </div>
        </section>
      }
      </div>
      <div class="shrink-0 border-t border-[var(--mat-sys-outline-variant)] px-3 py-2">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
          @if (twoUp() && candidates().length) {
        <div class="flex items-center gap-1 min-w-0">
          <button mat-icon-button data-candidate-previous class="!text-[var(--mat-sys-on-surface)] disabled:!text-[var(--mat-sys-outline)]"
                  [disabled]="candidateIndex() <= 0" [attr.aria-label]="I18N.gallery.compare.previous_candidate | translate"
                  (click)="moveCandidate(-1)"><mat-icon>chevron_left</mat-icon></button>
          <span class="min-w-0 truncate text-xs" aria-live="polite">{{ I18N.gallery.compare.candidate_position | translate:{ current: candidateIndex() + 1, total: candidates().length } }}</span>
          <button mat-icon-button data-candidate-next class="!text-[var(--mat-sys-on-surface)] disabled:!text-[var(--mat-sys-outline)]"
                  [disabled]="candidateIndex() >= candidates().length - 1" [attr.aria-label]="I18N.gallery.compare.next_candidate | translate"
                  (click)="moveCandidate(1)"><mat-icon>chevron_right</mat-icon></button>
        </div>
      }
          <span class="sr-only">{{ I18N.gallery.compare.queue | translate:{ count: candidates().length } }}</span>
          <div class="flex shrink-0 gap-1" role="group" [attr.aria-label]="I18N.gallery.compare.assign_target | translate">
            <button type="button" data-compare-target="reference" class="min-h-11 rounded border border-[var(--mat-sys-outline-variant)] px-2" [class.bg-[var(--mat-sys-secondary-container)]]="assignmentTarget() === 'reference'" [attr.aria-pressed]="assignmentTarget() === 'reference'" (click)="assignmentTarget.set('reference')">{{ I18N.gallery.compare.reference | translate }}</button>
            <button type="button" data-compare-target="candidate" class="min-h-11 rounded border border-[var(--mat-sys-outline-variant)] px-2" [class.bg-[var(--mat-sys-secondary-container)]]="assignmentTarget() === 'candidate'" [attr.aria-pressed]="assignmentTarget() === 'candidate'" (click)="assignmentTarget.set('candidate')">{{ I18N.gallery.compare.candidate | translate }}</button>
          </div>
          @if (removedPaths().size) {
            <button mat-button data-restore-comparison (click)="restorePanes()">{{ I18N.gallery.compare.restore | translate }}</button>
          }
        </div>
        <p class="sr-only" data-comparison-assignment>{{ I18N.gallery.compare.assign_hint | translate:{ target: ((assignmentTarget() === 'reference' ? I18N.gallery.compare.reference : I18N.gallery.compare.candidate) | translate) } }}</p>
        <div class="flex gap-2 overflow-x-auto" role="group" [attr.aria-label]="I18N.gallery.compare.queue_label | translate">
          @for (photo of panes(); track photo.path) {
            <button #candidateButton type="button" data-candidate-thumbnail [attr.data-path]="photo.path"
                    class="flex w-24 shrink-0 flex-col gap-1 rounded border border-[var(--mat-sys-outline-variant)] p-1 text-left focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
                    [class.bg-[var(--mat-sys-secondary-container)]]="activePath() === photo.path"
                    [attr.aria-pressed]="activePath() === photo.path"
                    [attr.aria-label]="I18N.gallery.compare.assign_photo | translate:{ target: ((assignmentTarget() === 'reference' ? I18N.gallery.compare.reference : I18N.gallery.compare.candidate) | translate), name: photo.filename }"
                    (click)="chooseCandidate(photo.path)">
              <img [src]="photo.path | thumbnailUrl:storedEdge:photo.preview_revision" alt="" class="h-12 w-full object-contain bg-neutral-950" />
              <span class="flex items-center gap-1 text-xs w-full"><mat-icon class="!text-sm !w-4 !h-4 shrink-0">{{ referencePath() === photo.path ? 'push_pin' : 'photo' }}</mat-icon><span class="truncate">{{ photo.filename }}</span></span>
            </button>
          }
        </div>
      </div>

    </div>
  `,
  host: { class: 'block h-full min-h-0', tabindex: '-1', '(keydown)': 'onInspectionKey($event)' },
})
export class ComparisonWorkspaceComponent {
  protected readonly I18N = i18nKeys();
  private readonly router = inject(Router);
  private readonly session = inject(ComparisonSessionService);
  private readonly data = this.session.snapshot();
  private readonly injector = inject(Injector);
  private readonly document = inject(DOCUMENT);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly cancelled = new Subject<void>();
  private closing = false;
  private readonly token = this.auth.token;
  private readonly owner = this.auth.identity();
  private readonly status = this.auth.status();
  private readonly guards = inject(StalenessGuardFactory);
  private readonly navigating = signal(false);
  private context = this.createContext();

  private createContext() {
    return this.guards.create(this.destroyRef, {
      requireEdition: false, track: 'status', valid: () => !this.closing && this.token === this.auth.token && this.owner === this.auth.identity() && this.status === this.auth.status(),
      onNavigate: () => { this.navigating.set(true); this.cancelled.next(); },
    });
  }
  private readonly imagePanes = viewChildren(SyncedZoomComponent);
  private readonly candidateButtons = viewChildren<ElementRef<HTMLButtonElement>>('candidateButton');

  protected readonly storedEdge = STORED_EDGE;
  protected readonly renderedEdge = RENDERED_EDGE;

  /** Each photo retains its own framing, including candidates outside two-up. */
  protected readonly linked = signal(true);
  protected readonly referencePath = signal(this.data.photos?.[0]?.path ?? null);
  protected readonly twoUp = signal(false);
  protected readonly assignmentTarget = signal<'reference' | 'candidate'>('candidate');
  protected readonly activePath = signal(this.data.photos?.[0]?.path ?? null);
  protected readonly removedPaths = signal(new Set<string>());
  private readonly candidatePath = signal(this.data.photos?.[1]?.path ?? null);
  private readonly paneZoom = signal(new Map<string, ZoomState>());
  private readonly readiness = signal(new Map<string, 'loading' | 'ready' | 'failed'>());
  private readonly renditions = signal(new Map<string, DisplayedRendition>());
  protected readonly inspectionOpen = signal(false);
  protected readonly inspectionState = signal<'idle' | 'loading' | 'ready' | 'partial'>('idle');
  protected readonly inspectionNotice = signal<string | null>(null);
  protected readonly loupe = signal(false);
  protected readonly loupeZoom = signal(3);
  private readonly faceRows = signal(new Map<string, PhotoFaceRow[]>());
  private readonly suggestions = signal(new Map<string, KeySubject>());
  protected readonly sharedPeople = computed(() => sharedInspectionPeople(this.visiblePhotos().map(photo => photo.path), this.faceRows()));

  constructor() {
    afterNextRender(() => this.host.nativeElement.focus({ preventScroll: true }));
    this.destroyRef.onDestroy(() => { this.closing = true; this.cancelled.next(); this.context.dispose(); });
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(event => {
      if (event instanceof NavigationCancel || event instanceof NavigationError) {
        this.context.dispose(); this.closing = false; this.context = this.createContext(); this.navigating.set(false);
        if (this.inspectionState() === 'loading') this.inspectionState.set('partial');
      }
    });
    effect(() => {
      const current = this.context.current();
      if (!this.closing && !this.navigating() && !current) {
        this.session.clear(); this.closing = true; this.cancelled.next();
        void this.router.navigateByUrl('/', { replaceUrl: true });
      }
    });
  }

  protected toggleInspection(): void {
    if (!this.context.current()) return;
    this.inspectionOpen.update(open => !open);
    if (this.inspectionOpen() && this.inspectionState() === 'idle') void this.loadInspection();
  }

  protected async loadInspection(): Promise<void> {
    const context = this.context;
    if (!context.current() || this.inspectionState() === 'loading') return;
    this.inspectionState.set('loading');
    const photos = [...new Map((this.data.photos ?? []).slice(0, MAX_COMPARE_PANES).map(photo => [photo.path, photo])).values()];
    const faces = new Map<string, PhotoFaceRow[]>();
    const suggestions = new Map<string, KeySubject>();
    let failed = false;
    await Promise.all([
      (async () => {
        try {
          const result = await firstValueFrom(this.api.post<{ key_subjects_by_path: Record<string, KeySubject> }>('/photos/key_subjects', { paths: photos.map(photo => photo.path) }).pipe(takeUntil(this.cancelled), takeUntilDestroyed(this.destroyRef)));
          for (const photo of photos) {
            const target = result.key_subjects_by_path?.[photo.path];
            if (target?.path === photo.path && (target.kind === 'person' || target.kind === 'subject') && target.coordinate_space === KEY_SUBJECT_COORDINATE_SPACE && normalizedInspectionBox(target.bbox)
              && Number.isFinite(target.image_width) && Number.isFinite(target.image_height) && target.image_width! > 0 && target.image_height! > 0) suggestions.set(photo.path, target);
          }
        } catch { failed = true; }
      })(),
      ...photos.map(async photo => {
        try {
          const result = await firstValueFrom(this.api.get<{ faces: PhotoFaceRow[] }>('/photo/faces', { path: photo.path }).pipe(takeUntil(this.cancelled), takeUntilDestroyed(this.destroyRef)));
          // Keep unusable occurrences too: dropping one would make a duplicate
          // saved-person assignment look like an unambiguous correspondence.
          faces.set(photo.path, result.faces ?? []);
        } catch { failed = true; }
      }),
    ]);
    if (!context.current()) return;
    this.faceRows.set(faces); this.suggestions.set(suggestions);
    this.inspectionState.set(failed ? 'partial' : 'ready');
  }

  protected setLoupeZoom(event: Event): void {
    const value = Number((event.target as HTMLSelectElement).value);
    if ([2, 3, 5].includes(value)) this.loupeZoom.set(value);
  }

  protected onInspectionKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && !event.isComposing && !event.repeat) {
      event.preventDefault(); event.stopPropagation();
      if (this.inspectionOpen()) {
        this.inspectionOpen.set(false);
        this.host.nativeElement.querySelector<HTMLButtonElement>('[data-inspection-toggle]')?.focus();
      } else this.close();
      return;
    }
    if (isTypingContext(event) || event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey || !this.context.current()) return;
    if (event.key.toLowerCase() === 'z') { event.preventDefault(); event.stopPropagation(); this.loupe.update(active => !active); }
  }

  protected frameSuggestion(path: string): void {
    const target = this.suggestions().get(path);
    const box = normalizedInspectionBox(target?.bbox);
    if (box) this.frameBoxes(new Map([[path, box]]));
  }

  protected frameFace(path: string, event: Event): void {
    const select = event.target as HTMLSelectElement;
    if (!select.value) return;
    const face = this.faceRows().get(path)?.find(face => face.id === Number(select.value));
    const box = normalizedInspectionBox(face?.box);
    select.value = '';
    if (box) this.frameBoxes(new Map([[path, box]]));
  }

  protected frameSharedPerson(event: Event): void {
    const select = event.target as HTMLSelectElement;
    if (!select.value) return;
    const person = this.sharedPeople().find(person => person.id === Number(select.value));
    select.value = '';
    if (person) this.frameBoxes(person.boxes);
  }

  private frameBoxes(boxes: ReadonlyMap<string, NormalizedBox>): void {
    if (!this.context.current()) return;
    const frames = new Map(this.paneZoom());
    for (const [path, box] of boxes) {
      const photo = this.visiblePhotos().find(photo => photo.path === path);
      const pane = this.imagePanes().find(pane => pane.frameKey() === path);
      const detected = this.suggestions().get(path);
      const aspect = detected?.image_width && detected.image_height ? detected.image_width / detected.image_height
        : photo?.image_width && photo.image_height ? photo.image_width / photo.image_height : undefined;
      const frame = photo && pane?.zoomForRegion(box, aspect);
      if (!frame) { this.inspectionNotice.set(this.I18N.gallery.compare.inspection.manual_fallback); return; }
      frames.set(path, frame);
    }
    this.linked.set(false);
    this.paneZoom.set(frames);
    this.inspectionNotice.set(this.I18N.gallery.compare.inspection.review_link);
  }

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

  protected readonly paneStates = computed(() => this.visiblePhotos().map(photo => {
    const zoom = this.paneZoom().get(photo.path) ?? FIT_ZOOM;
    const rendition = this.renditions().get(photo.path);
    return {
      photo, zoom, rendition, fitted: zoom.scale === 1 && zoom.tx === 0 && zoom.ty === 0,
      faces: (this.faceRows().get(photo.path) ?? []).filter(face => normalizedInspectionBox(face.box) && Number.isInteger(face.id) && Number.isInteger(face.face_index)), suggestion: this.suggestions().get(photo.path),
      zoomOutDisabled: this.linked() ? this.panes().some(p => (this.paneZoom().get(p.path) ?? FIT_ZOOM).scale <= 1) : zoom.scale <= 1,
      zoomInDisabled: this.linked() ? this.panes().some(p => (this.paneZoom().get(p.path) ?? FIT_ZOOM).scale >= 8) : zoom.scale >= 8,
      previewFailed: this.readiness().get(photo.path) === 'failed',
      kindKey: this.I18N.gallery.compare.rendition[rendition?.kind ?? 'thumbnail'],
      phaseKey: this.readiness().get(photo.path) === 'failed' && rendition?.kind === 'thumbnail' ? this.I18N.gallery.compare.rendition.fallback : this.I18N.gallery.compare.rendition[rendition?.phase ?? 'loading'],
      scaleLabel: `${Number(zoom.scale.toFixed(1))}×`,
    };
  }));

  protected readonly zoomed = computed(() => [...this.paneZoom().values()].some(frame =>
    frame.scale !== FIT_ZOOM.scale || frame.tx !== 0 || frame.ty !== 0));

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
    if (!this.context.current() || !this.panes().some(photo => photo.path === path)) return;
    if (this.assignmentTarget() === 'reference') {
      const previous = this.referencePath();
      if (path === this.candidatePath()) this.candidatePath.set(previous);
      this.referencePath.set(path);
      this.activePath.set(path);
      this.twoUp.set(true);
      return;
    }
    this.activePath.set(path);
    if (path === this.referencePath()) {
      const candidate = this.candidates()[this.candidateIndex()];
      if (candidate) {
        this.referencePath.set(candidate.path);
        this.candidatePath.set(path);
        this.twoUp.set(true);
      }
      return;
    }
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
    this.paneZoom.update(values => { const next = new Map(values); next.delete(path); return next; });
    this.readiness.update(values => { const next = new Map(values); next.delete(path); return next; });
    this.renditions.update(values => { const next = new Map(values); next.delete(path); return next; });
    afterNextRender(() => {
      if (this.document.activeElement !== this.document.body && this.document.activeElement !== focusBefore) return;
      this.candidateButtons().find(button => button.nativeElement.dataset['path'] === this.activePath())?.nativeElement.focus();
    }, { injector: this.injector });
  }

  protected restorePanes(): void {
    this.removedPaths.set(new Set());
  }

  protected onZoom(path: string, state: ZoomState): void {
    // A hidden two-up candidate may still finish an old gesture after unmounting.
    if (!this.visiblePhotos().some(photo => photo.path === path)) return;
    if (![state.scale, state.tx, state.ty].every(Number.isFinite) ||
        state.scale < SyncedZoomComponent.MIN_SCALE || state.scale > SyncedZoomComponent.MAX_SCALE) return;
    const frames = this.paneZoom();
    if (!this.linked()) {
      this.paneZoom.set(new Map(frames).set(path, { ...state }));
      return;
    }
    const source = frames.get(path) ?? FIT_ZOOM;
    const members = this.panes().map(photo => ({ path: photo.path, frame: frames.get(photo.path) ?? FIT_ZOOM }));
    // Compose the same affine gesture over every crop: scale existing offsets,
    // then add the source gesture's residual pan. Corresponding manually aligned
    // points therefore move together, even when panes started at different scales.
    // Stop the whole group at the first scale limit, preserving relative scales.
    const minimum = Math.max(...members.map(({ frame }) => SyncedZoomComponent.MIN_SCALE / frame.scale));
    const maximum = Math.min(...members.map(({ frame }) => SyncedZoomComponent.MAX_SCALE / frame.scale));
    const ratio = Math.max(minimum, Math.min(maximum, state.scale / source.scale));
    this.paneZoom.set(new Map(members.map(({ path: memberPath, frame }) => [memberPath, {
      scale: frame.scale * ratio,
      tx: frame.tx * ratio + state.tx - source.tx * ratio,
      ty: frame.ty * ratio + state.ty - source.ty * ratio,
    }])));
  }

  protected toggleLinked(): void {
    this.linked.update(linked => !linked);
  }

  protected setRendition(path: string, rendition: DisplayedRendition): void {
    if (!this.visiblePhotos().some(photo => photo.path === path)) return;
    this.renditions.update(values => new Map(values).set(path, rendition));
  }

  protected stepZoom(path: string, direction: number): void {
    const frame = this.paneZoom().get(path) ?? FIT_ZOOM;
    this.onZoom(path, { ...frame, scale: Math.max(1, Math.min(8, frame.scale * (direction > 0 ? 1.5 : 1 / 1.5))) });
  }

  protected fitPane(path: string): void {
    if (!this.visiblePhotos().some(photo => photo.path === path)) return;
    if (this.linked()) this.resetZoom();
    else this.paneZoom.update(values => new Map(values).set(path, { ...FIT_ZOOM }));
  }

  protected setReadiness(path: string, state: 'loading' | 'ready' | 'failed'): void {
    if (!this.panes().some(photo => photo.path === path)) return;
    this.readiness.update(values => new Map(values).set(path, state));
  }

  protected resetZoom(): void {
    this.paneZoom.set(new Map());
  }

  protected close(): void {
    if (this.closing || this.navigating()) return;
    this.closing = true;
    void this.router.navigateByUrl(this.data.returnUrl);
  }
}
