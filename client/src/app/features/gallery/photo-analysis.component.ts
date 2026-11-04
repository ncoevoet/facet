import { Component, Pipe, PipeTransform, inject, signal, computed, input, effect, untracked, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';
import { Router } from '@angular/router';
import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom, Subject, takeUntil } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, STORED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import type { MediaCritiqueResponse } from '../../core/api/types';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';

interface FaceMarker {
  bbox: number[] | null;
  eyes: number[][];
  eyes_open_score: number | null;
  is_blink: boolean;
}

type CategoryReason = MediaCritiqueResponse['category_reason'];

type CategoryMismatch = NonNullable<CategoryReason['rejected']>[number]['mismatch'];

interface SkinTonePenalty {
  cast: string;
  delta: number;
}

/** The generated response, with the advisory map the schema leaves open narrowed to the two flags the server sends. */
type CritiqueResponse = Omit<MediaCritiqueResponse, 'penalties'> & {
  penalties: { blink?: boolean; skin_tone?: SkinTonePenalty };
};

@Pipe({ name: 'contributionColor', standalone: true })
export class ContributionColorPipe implements PipeTransform {
  transform(value: number, weight: number): string {
    const score = weight > 0 ? value / weight : 0;
    if (score >= 7.5) return 'text-[var(--mat-sys-primary)]';
    if (score < 5.0) return 'text-[var(--mat-sys-error)]';
    return 'text-[var(--mat-sys-on-surface)]';
  }
}

@Pipe({ name: 'categoryReason', standalone: true })
export class CategoryReasonPipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(reason: CategoryReason): string {
    if (reason.reason_key === 'unavailable') {
      return this.i18n.t(I18N.critique.calculation_unavailable);
    }
    if (reason.reason_key === 'override') {
      return this.i18n.t(I18N.critique.reason.override, { category: reason.category });
    }
    if (reason.reason_key === 'default') {
      return this.i18n.t(I18N.critique.reason.default);
    }
    if (!reason.details?.length) {
      return this.i18n.t(I18N.critique.reason.matched_generic);
    }
    const details = reason.details.map(d => {
      if (d.key === 'tags') {
        return this.i18n.t(I18N.critique.reason.tags, { tags: (d.tags ?? []).join(', ') });
      }
      return this.i18n.t(`critique.reason.${d.key}`, {
        value: String(d.value ?? ''),
        threshold: String(d.threshold ?? ''),
      });
    });
    return `${this.i18n.t(I18N.critique.reason.classified_as, { category: reason.category })}: ${details.join('; ')}`;
  }
}

@Pipe({ name: 'mismatchReason', standalone: true })
export class MismatchReasonPipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(mismatch: CategoryMismatch): string {
    const key = mismatch.key;

    if (key === 'required_tags') {
      const tags = (mismatch.required as string[] || []).slice(0, 3).join(', ');
      const suffix = (mismatch.required as string[] || []).length > 3 ? ', …' : '';
      return this.i18n.t(I18N.critique.reason.mismatch.required_tags, { tags: tags + suffix });
    }
    if (key === 'excluded_tags') {
      return this.i18n.t(I18N.critique.reason.mismatch.excluded_tags, { tags: (mismatch.actual as string[]).join(', ') });
    }

    // Boolean filters — pick the right key based on required value
    if (['has_face', 'is_monochrome', 'is_silhouette', 'is_group_portrait'].includes(key)) {
      const suffix = mismatch.required ? '' : '_false';
      return this.i18n.t(`critique.reason.mismatch.${key}${suffix}`);
    }

    // Numeric filters
    if (mismatch.actual === null || mismatch.actual === undefined) {
      return this.i18n.t(I18N.critique.reason.mismatch.no_value);
    }
    return this.i18n.t(`critique.reason.mismatch.${key}`, {
      required: String(mismatch.required ?? ''),
      actual: String(mismatch.actual ?? ''),
    });
  }
}

/**
 * Distortion ids come from a config-replaceable server vocabulary, so an
 * unknown id has no ``critique.distortion.<id>`` bundle entry. When the
 * translation resolves to the key unchanged, fall back to a humanized form of
 * the id (underscores → spaces) rather than rendering the raw dotted key.
 */
@Pipe({ name: 'distortionLabel', standalone: true, pure: false })
export class DistortionLabelPipe implements PipeTransform {
  private i18n = inject(I18nService);

  transform(id: string): string {
    const key = `critique.distortion.${id}`;
    const label = this.i18n.t(key);
    return label === key ? id.replace(/_/g, ' ') : label;
  }
}

// Module-level consts, not direct class-field initializers: Vite's test transform
// snapshots an imported binding used as a field initializer before a
// lazily-initialised shared chunk sets it.
const STORED_EDGE = STORED_THUMBNAIL_EDGE;

@Component({
  selector: 'app-photo-analysis',
  standalone: true,
  imports: [
    MatButtonModule, MatIconModule, MatProgressSpinnerModule, ContextHelpComponent,
    DecimalPipe, PercentPipe, TranslatePipe, ThumbnailUrlPipe, ContributionColorPipe, CategoryReasonPipe, MismatchReasonPipe, DistortionLabelPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: '@container block min-w-0' },
  template: `
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (error(); as e) {
        <div class="flex flex-col items-center gap-2 py-8 text-[var(--mat-sys-error)]">
          <mat-icon class="!text-4xl !w-10 !h-10">error_outline</mat-icon>
          <p class="text-sm">{{ e }}</p>
          <button mat-button data-analysis-retry (click)="retry()">{{ I18N.gallery.load_error.retry | translate }}</button>
        </div>
      } @else if (critique(); as c) {
        <!-- Visual "why this score" overlay -->
        @if (overlaySupported()) {
          <div class="relative mb-4 rounded-lg overflow-hidden bg-black/20">

            @if (overlayOn()) {
            <!-- Stored thumbnail: the saliency overlay is computed from it. -->
            <img [src]="photoPath() | thumbnailUrl:storedEdge" class="block w-full" alt="" />

              <img [src]="overlayUrl()" (error)="onOverlayError($event)" class="absolute inset-0 w-full h-full opacity-60 mix-blend-multiply" alt="" />
              <svg class="absolute inset-0 w-full h-full" viewBox="0 0 1 1" preserveAspectRatio="none">
                @for (f of faceMarkers(); track $index) {
                  @if (f.bbox; as b) {
                    <rect [attr.x]="b[0]" [attr.y]="b[1]" [attr.width]="b[2] - b[0]" [attr.height]="b[3] - b[1]"
                          fill="none" [attr.stroke]="f.is_blink ? '#fbbf24' : '#22c55e'" stroke-width="0.005" />
                  }
                  @for (e of f.eyes; track $index) {
                    <circle [attr.cx]="e[0]" [attr.cy]="e[1]" r="0.006" [attr.fill]="f.is_blink ? '#fbbf24' : '#22c55e'" />
                  }
                }
              </svg>
            }
            <button mat-stroked-button [class.!top-2]="overlayOn()" [class.!right-2]="overlayOn()" [class.!bg-[var(--mat-sys-surface)]/80]="overlayOn()" [class.!absolute]="overlayOn()" (click)="toggleOverlay()">
              <mat-icon>{{ overlayOn() ? 'visibility_off' : 'visibility' }}</mat-icon>
              {{ (overlayOn() ? I18N.critique.overlay_hide : I18N.critique.overlay_show) | translate }}
            </button>
          </div>
        }

        <!-- Category reason -->
        <div class="text-sm mb-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
          <div class="text-xs font-medium text-[var(--mat-sys-on-surface-variant)] mb-1">{{ I18N.critique.category_reason | translate }}</div>
          <div>{{ c.category_reason | categoryReason }}</div>
          @if (c.category_reason.rejected?.length) {
            <button class="mt-2 text-xs text-[var(--mat-sys-on-surface-variant)] hover:underline flex items-center gap-1 cursor-pointer"
                    [attr.aria-expanded]="showRejected()"
                    (click)="showRejected.set(!showRejected())">
              <mat-icon class="!text-sm !w-4 !h-4 !leading-4">{{ showRejected() ? 'expand_less' : 'expand_more' }}</mat-icon>
              {{ I18N.critique.reason.rejected_header | translate:{ count: '' + c.category_reason.rejected!.length } }}
            </button>
            @if (showRejected()) {
              <ul class="mt-1 space-y-0.5 text-xs">
                @for (r of c.category_reason.rejected; track r.category) {
                  <li class="flex items-center gap-1.5">
                    <mat-icon class="!text-xs !w-3.5 !h-3.5 !leading-3.5 text-[var(--mat-sys-error)] shrink-0">close</mat-icon>
                    <span class="font-medium">{{ r.category }}</span>
                    <span class="text-[var(--mat-sys-on-surface-variant)]">— {{ r.mismatch | mismatchReason }}</span>
                  </li>
                }
              </ul>
            }
          }
        </div>

        <div class="text-sm mb-3" data-testid="score-calculation-context">
          <div>{{ I18N.critique.stored_score | translate }}:
            @if (c.aggregate !== null && c.aggregate !== undefined) { {{ c.aggregate | number:'1.2-2' }} }
            @else if (c.stored_score_state === 'missing') { {{ I18N.critique.stored_state.missing | translate }} }
            @else if (c.stored_score_state === 'invalid') { {{ I18N.critique.stored_state.invalid | translate }} }
            @else { {{ I18N.critique.stored_unavailable | translate }} }
          </div>
          @if (c.current_formula_score !== null && c.current_formula_score !== undefined) {
            <app-context-help [label]="I18N.critique.current_formula" [keys]="calculationHelp()" />
            @if (c.stored_score_matches_current_formula === false) {
              <p class="text-xs text-[var(--mat-sys-on-surface)]">{{ I18N.critique.different_score | translate }}</p>
            }
          } @else {
            @if (c.explanation_unavailable_reason; as reason) {
              <p class="text-xs text-[var(--mat-sys-on-surface-variant)]" data-testid="unavailable-reason">{{ 'critique.unavailable_reason.' + reason | translate }}</p>
            } @else {
              <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.critique.calculation_unavailable | translate }}</p>
            }
          }
        </div>

        <!-- Score breakdown table -->
        <div class="text-xs font-medium text-[var(--mat-sys-on-surface-variant)] mb-2">{{ I18N.critique.breakdown | translate }}</div>
        <table class="w-full table-fixed text-sm mb-4" [attr.aria-label]="I18N.critique.breakdown | translate">
          <thead class="text-xs text-[var(--mat-sys-on-surface-variant)]">
            <tr>
              <th scope="col" class="w-[40%] pb-2 text-start font-medium">{{ I18N.critique.metric | translate }}</th>
              <th scope="col" class="pb-2 text-end font-medium break-words">{{ I18N.critique.value | translate }}</th>
              <th scope="col" class="pb-2 text-end font-medium break-words">{{ I18N.critique.weight | translate }}</th>
              <th scope="col" class="pb-2 text-end font-medium break-words">{{ I18N.critique.contribution_label | translate }}</th>
            </tr>
          </thead>
          <tbody>
            @for (item of c.breakdown; track item.metric_key) {
              <tr class="border-b border-[var(--mat-sys-outline-variant)]/30">
                <th scope="row" class="py-2 pe-2 text-start font-normal break-words">{{ 'critique.metrics.' + item.metric_key | translate }}</th>
                <td class="text-end py-2" [class]="item.value | contributionColor:1">{{ item.value }}</td>
                <td class="text-end py-2 text-[var(--mat-sys-on-surface-variant)]">{{ item.weight | percent:'1.0-0' }}</td>
                <td class="text-end py-2 font-medium" [class]="item.contribution | contributionColor:item.weight">{{ item.contribution | number:'1.2-2' }}</td>
              </tr>
            }
          </tbody>
          @if (c.current_formula_score !== null && c.current_formula_score !== undefined) {
            <tfoot data-testid="score-calculation-total">
              <tr><th scope="row" colspan="3" class="py-2 pe-2 text-start font-normal">{{ I18N.critique.adjustments | translate }}</th>
                <td class="py-2 text-end">{{ c.native_adjustment | number:'1.2-2' }}</td></tr>
              <tr class="font-medium"><th scope="row" colspan="3" class="py-2 pe-2 text-start font-medium">{{ I18N.critique.current_formula | translate }}</th>
                <td class="py-2 text-end">{{ c.current_formula_score | number:'1.2-2' }}</td></tr>
            </tfoot>
          }
        </table>

        @if (observationSections().length) {
          <div class="mb-3 grid grid-cols-1 gap-3 @min-[440px]:grid-cols-2">
            @for (section of observationSections(); track section.label) {
              <div>
                <div class="mb-1 text-xs uppercase tracking-wider" [class]="section.tone">{{ section.label | translate }}</div>
                <ul class="space-y-0.5 text-sm">
                  @for (item of section.items; track item.metric_key) {
                    <li class="flex items-center gap-1.5">
                      <mat-icon class="!h-4 !w-4 !text-sm !leading-4 shrink-0" [class]="section.tone">{{ section.icon }}</mat-icon>
                      {{ 'critique.metrics.' + item.metric_key | translate }} ({{ item.value }})
                    </li>
                  }
                </ul>
              </div>
            }
          </div>
        }

        <!-- Detected distortions (advisory, zero-shot) -->
        @if (c.distortions?.length) {
          <div class="mb-3">
            <div class="text-xs uppercase tracking-wider text-[var(--mat-sys-on-surface)] mb-1">{{ I18N.critique.distortions | translate }}</div>
            <div class="flex flex-wrap gap-1.5">
              @for (d of c.distortions; track d) {
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-amber-400/10 text-[var(--mat-sys-on-surface)]">
                  <mat-icon class="!text-xs !w-3.5 !h-3.5 !leading-3.5">warning_amber</mat-icon>
                  {{ d | distortionLabel }}
                </span>
              }
            </div>
          </div>
        }

        <!-- Suggestions -->
        @if (c.suggestions?.length) {
          <div class="mb-3">
            <div class="text-xs font-medium text-[var(--mat-sys-on-surface-variant)] mb-1">{{ I18N.critique.suggestions | translate }}</div>
            <ul class="text-sm space-y-0.5">
              @for (tip of c.suggestions; track tip) {
                <li class="flex items-center gap-1.5">
                  <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-[var(--mat-sys-primary)] shrink-0">lightbulb</mat-icon>
                  {{ 'critique.suggestion.' + tip | translate }}
                </li>
              }
            </ul>
          </div>
        }

        <!-- VLM Critique -->
        @if (c.vlm_critique) {
          @if (c.vlm_source === 'cached') {
            <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.critique.cached_commentary | translate }}</p>
          }
          <div class="mt-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
            <div class="flex items-center mb-1">
              <div class="flex-1 text-xs font-medium text-[var(--mat-sys-on-surface-variant)]">{{ I18N.critique.vlm_title | translate }}</div>
              @if (vlmRefreshing()) {
                <mat-spinner diameter="16" [attr.aria-label]="I18N.ui.labels.loading | translate" />
              } @else if (auth.isEdition() && vlmAvailable()) {
                <button mat-icon-button class="!min-w-11 !min-h-11 shrink-0"
                        [attr.aria-label]="I18N.critique.vlm_refresh | translate"
                        [title]="I18N.critique.vlm_refresh | translate"
                        (click)="refreshVlm()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">refresh</mat-icon>
                </button>
              }
            </div>
            <p class="text-sm whitespace-pre-line">{{ c.vlm_critique }}</p>
          </div>
        }

        @if (auth.isEdition() && vlmAvailable() && (c.vlm_available || c.vlm_translation_missing) && (!c.vlm_critique || c.vlm_translation_missing)) {
          <button mat-stroked-button data-analysis-generate [disabled]="vlmRefreshing()" (click)="requestCommentary()">
            <mat-icon aria-hidden="true">auto_awesome</mat-icon>{{ (c.vlm_translation_missing ? I18N.critique.translate_action : I18N.critique.generate_action) | translate }}
          </button>
        }
        @if (generationError()) { <p role="status" class="text-sm">{{ I18N.critique.error_fallback | translate }}</p> }

        <!-- Penalties -->
        @if (hasPenalties()) {
          <div class="mt-3 text-xs text-[var(--mat-sys-on-surface-variant)]">
            <span class="uppercase tracking-wider">{{ I18N.critique.advisories | translate }}:</span>
            @if (c.penalties.blink) { <span class="ml-2 text-[var(--mat-sys-error)]">{{ I18N.critique.penalty.blink | translate }}</span> }
            @if (skinTone(); as st) { <span class="ml-2 text-[var(--mat-sys-on-surface)]">{{ I18N.critique.penalty.skin_tone | translate:{ cast: ('critique.skin_cast.' + st.cast | translate), delta: '' + st.delta } }}</span> }
          </div>
        }
      }

  `,
})
export class PhotoAnalysisComponent {
  protected readonly I18N = i18nKeys();
  protected readonly storedEdge = STORED_EDGE;
  private readonly api = inject(ApiService);
  protected readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snack = inject(MatSnackBar);
  readonly photoPath = input.required<string>();
  readonly vlmAvailable = input(false);
  private readonly destroyRef = inject(DestroyRef);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly router = inject(Router);
  private readonly initialOwner = this.auth.identity();
  private readonly initialUrl = this.router.url;
  private readonly pendingNavigation = trackPendingNavigation({ started: () => {
    this.cancelRequests.next(); this.resetPhotoState();
  } });
  private readonly reload = signal(0);
  private readonly cancelRequests = new Subject<void>();
  private epoch = 0;
  private context: { path: string; locale: string; current: () => boolean } | null = null;
  protected readonly generationError = signal(false);

  constructor() {
    effect(onCleanup => {
      const path = this.photoPath();
      const locale = this.i18n.locale();
      const owner = this.auth.identity();
      this.auth.status();
      const token = this.auth.token;
      const edition = this.auth.isEdition();
      const vlm = this.vlmAvailable();
      const pending = this.pendingNavigation();
      this.reload();
      const epoch = ++this.epoch;
      this.cancelRequests.next();
      this.context = null;
      this.resetPhotoState();
      if (pending || owner !== this.initialOwner || this.router.url !== this.initialUrl) return;
      const guard = this.guards.create(this.destroyRef, {
        track: 'status', requireEdition: false,
        valid: () => this.epoch === epoch && !this.pendingNavigation()
          && this.auth.identity() === owner && this.auth.token === token && this.auth.isEdition() === edition
          && this.photoPath() === path && this.i18n.locale() === locale,
      });
      onCleanup(() => { this.cancelRequests.next(); guard.dispose(); });
      this.context = { path, locale, current: guard.current };
      untracked(() => { void this.loadEvidence(this.context!, vlm); });
    });
    this.destroyRef.onDestroy(() => { this.cancelRequests.next(); this.cancelRequests.complete(); });
  }

  private resetPhotoState(): void {
    this.critique.set(null); this.error.set(null); this.generationError.set(false);
    this.overlayOn.set(false); this.faceMarkers.set([]); this.showRejected.set(false);
    this.vlmRefreshing.set(false); this.loading.set(false);
  }

  protected retry(): void { this.reload.update(value => value + 1); }


  protected readonly loading = signal(true);
  protected readonly critique = signal<CritiqueResponse | null>(null);
  protected readonly observationSections = computed(() => {
    const critique = this.critique();
    return [
      { label: I18N.critique.strengths, icon: 'check_circle', tone: 'text-[var(--mat-sys-primary)]', items: critique?.strengths ?? [] },
      { label: I18N.critique.weaknesses, icon: 'warning', tone: 'text-[var(--mat-sys-error)]', items: critique?.weaknesses ?? [] },
    ].filter(section => section.items.length);
  });
  protected readonly calculationHelp = computed(() => {
    const basis = this.critique()?.normalization_basis;
    return basis
      ? [I18N.critique.calculation_note, `critique.normalization_basis.${basis}`]
      : [I18N.critique.calculation_note];
  });
  protected readonly error = signal<string | null>(null);
  protected readonly showRejected = signal(false);
  protected readonly overlayOn = signal(false);
  protected readonly faceMarkers = signal<FaceMarker[]>([]);
  protected readonly overlaySupported = computed(() => this.auth.hasFeature('show_saliency_overlay'));
  protected readonly overlayUrl = computed(
    () => `/api/saliency_overlay?path=${encodeURIComponent(this.photoPath())}`,
  );

  protected async toggleOverlay(): Promise<void> {
    const context = this.context;
    if (!context?.current()) return;
    const next = !this.overlayOn();
    this.overlayOn.set(next);
    if (next && this.faceMarkers().length === 0) {
      try {
        const res = await firstValueFrom(
          this.api.get<{ faces: FaceMarker[] }>('/photo/face_markers', { path: context.path }).pipe(takeUntil(this.cancelRequests)),
        );
        if (context.current() && this.overlayOn()) this.faceMarkers.set(res.faces ?? []);
      } catch {
        // Face boxes are an optional embellishment; the heatmap still shows.
      }
    }
  }

  protected onOverlayError(event?: Event): void {
    if (!this.context?.current()) return;
    if (event) {
      const image = event.target;
      if (!(image instanceof HTMLImageElement) || (image.currentSrc || image.src) !== new URL(this.overlayUrl(), document.baseURI).href) return;
    }
    this.overlayOn.set(false);
    this.snack.open(this.i18n.t(I18N.critique.overlay_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
  }
  protected readonly hasPenalties = computed(() => {
    const c = this.critique();
    return !!(c && Object.keys(c.penalties).length > 0);
  });

  protected readonly skinTone = computed<SkinTonePenalty | null>(
    () => this.critique()?.penalties.skin_tone ?? null,
  );

  protected readonly vlmRefreshing = signal(false);

  private async loadEvidence(context: NonNullable<PhotoAnalysisComponent['context']>, vlm: boolean): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(this.api.get<CritiqueResponse>('/critique', {
        path: context.path, mode: vlm ? 'vlm' : 'rule', lang: context.locale,
      }).pipe(takeUntil(this.cancelRequests)));
      if (context.current()) this.critique.set(res);
    } catch (err: unknown) {
      if (context.current()) this.error.set(err instanceof Error ? err.message : this.i18n.t(I18N.critique.error_fallback));
    } finally {
      if (context.current()) this.loading.set(false);
    }
  }

  protected async requestCommentary(): Promise<void> { await this.requestVlm(false); }

  protected async refreshVlm(): Promise<void> {
    await this.requestVlm(true);
  }

  private async requestVlm(refresh: boolean): Promise<void> {
    const context = this.context;
    if (!context?.current() || !this.auth.isEdition() || !this.vlmAvailable() || this.vlmRefreshing()) return;
    this.generationError.set(false);
    this.vlmRefreshing.set(true);
    try {
      const res = await firstValueFrom(
        this.api.post<CritiqueResponse>('/critique/vlm', {
          path: context.path, lang: context.locale, refresh,
        }).pipe(takeUntil(this.cancelRequests)),
      );
      if (context.current()) this.critique.set(res);
    } catch {
      if (context.current()) this.generationError.set(true);
    } finally {
      if (context.current()) this.vlmRefreshing.set(false);
    }
  }
}
