import { Component, Pipe, PipeTransform, inject, signal, computed, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';
import { MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, STORED_THUMBNAIL_EDGE } from '../../shared/pipes/thumbnail-url.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import type { MediaCritiqueResponse } from '../../core/api/types';

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
    if (score >= 7.5) return 'text-green-400';
    if (score < 5.0) return 'text-red-400';
    return 'text-[var(--mat-sys-primary)]';
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
  selector: 'app-photo-critique-dialog',
  standalone: true,
  imports: [
    MatDialogModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule,
    DecimalPipe, PercentPipe, TranslatePipe, ThumbnailUrlPipe, ContributionColorPipe, CategoryReasonPipe, MismatchReasonPipe, DistortionLabelPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2 truncate">
      <mat-icon>analytics</mat-icon>
      <span class="flex-1">{{ I18N.critique.title | translate }}</span>
      <button mat-icon-button mat-dialog-close class="shrink-0 !-mt-1 !-mr-2" [attr.aria-label]="I18N.critique.close | translate">
        <mat-icon>close</mat-icon>
      </button>
    </h2>
    <mat-dialog-content class="!max-h-[70vh]">
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (error(); as e) {
        <div class="flex flex-col items-center gap-2 py-8 text-red-400">
          <mat-icon class="!text-4xl !w-10 !h-10">error_outline</mat-icon>
          <p class="text-sm">{{ e }}</p>
        </div>
      } @else if (critique(); as c) {
        <!-- Visual "why this score" overlay -->
        @if (overlaySupported()) {
          <div class="relative mb-4 rounded-lg overflow-hidden bg-black/20">
            <!-- Stored thumbnail: the saliency overlay is computed from it. -->
            <img [src]="data.photoPath | thumbnailUrl:storedEdge" class="block w-full" alt="" />
            @if (overlayOn()) {
              <img [src]="overlayUrl()" (error)="onOverlayError()" class="absolute inset-0 w-full h-full opacity-60 mix-blend-multiply" alt="" />
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
            <button mat-stroked-button class="!absolute !top-2 !right-2 !bg-[var(--mat-sys-surface)]/80" (click)="toggleOverlay()">
              <mat-icon>{{ overlayOn() ? 'visibility_off' : 'visibility' }}</mat-icon>
              {{ (overlayOn() ? I18N.critique.overlay_hide : I18N.critique.overlay_show) | translate }}
            </button>
          </div>
        }

        <!-- Category reason -->
        <div class="text-sm mb-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
          <div class="text-xs uppercase tracking-wider opacity-50 mb-1">{{ I18N.critique.category_reason | translate }}</div>
          <div>{{ c.category_reason | categoryReason }}</div>
          @if (c.category_reason.rejected?.length) {
            <button class="mt-2 text-xs opacity-50 hover:opacity-80 flex items-center gap-1 cursor-pointer"
                    (click)="showRejected.set(!showRejected())">
              <mat-icon class="!text-sm !w-4 !h-4 !leading-4">{{ showRejected() ? 'expand_less' : 'expand_more' }}</mat-icon>
              {{ I18N.critique.reason.rejected_header | translate:{ count: '' + c.category_reason.rejected!.length } }}
            </button>
            @if (showRejected()) {
              <ul class="mt-1 space-y-0.5 text-xs">
                @for (r of c.category_reason.rejected; track r.category) {
                  <li class="flex items-center gap-1.5 opacity-70">
                    <mat-icon class="!text-xs !w-3.5 !h-3.5 !leading-3.5 text-red-400/60 shrink-0">close</mat-icon>
                    <span class="font-medium">{{ r.category }}</span>
                    <span class="opacity-60">— {{ r.mismatch | mismatchReason }}</span>
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
            <p class="text-xs opacity-60">{{ I18N.critique.calculation_note | translate }}</p>
            @if (c.normalization_basis; as basis) {
              <p class="text-xs opacity-60" data-testid="normalization-basis">{{ 'critique.normalization_basis.' + basis | translate }}</p>
            }
            @if (c.stored_score_matches_current_formula === false) {
              <p class="text-xs text-amber-400">{{ I18N.critique.different_score | translate }}</p>
            }
          } @else {
            @if (c.explanation_unavailable_reason; as reason) {
              <p class="text-xs opacity-60" data-testid="unavailable-reason">{{ 'critique.unavailable_reason.' + reason | translate }}</p>
            } @else {
              <p class="text-xs opacity-60">{{ I18N.critique.calculation_unavailable | translate }}</p>
            }
          }
        </div>

        <!-- Score breakdown table -->
        <div class="text-xs uppercase tracking-wider opacity-50 mb-2">{{ I18N.critique.breakdown | translate }}</div>
        <table class="w-full text-sm mb-4">
          <tbody>
            @for (item of c.breakdown; track item.metric_key) {
              <tr class="border-b border-[var(--mat-sys-outline-variant)]/30">
                <td class="py-1">{{ 'critique.metrics.' + item.metric_key | translate }}</td>
                <td class="text-right py-1" [class]="item.value | contributionColor:1">{{ item.value }}</td>
                <td class="text-right py-1 opacity-60">{{ item.weight | percent:'1.0-0' }}</td>
                <td class="text-right py-1 font-medium" [class]="item.contribution | contributionColor:item.weight">{{ item.contribution | number:'1.2-2' }}</td>
              </tr>
            }
          </tbody>
          @if (c.current_formula_score !== null && c.current_formula_score !== undefined) {
            <tfoot data-testid="score-calculation-total">
              <tr><td colspan="3">{{ I18N.critique.adjustments | translate }}</td>
                <td class="text-right">{{ c.native_adjustment | number:'1.2-2' }}</td></tr>
              <tr class="font-medium"><td colspan="3">{{ I18N.critique.current_formula | translate }}</td>
                <td class="text-right">{{ c.current_formula_score | number:'1.2-2' }}</td></tr>
            </tfoot>
          }
        </table>

        <!-- Strengths & Weaknesses side by side -->
        @if (c.strengths?.length || c.weaknesses?.length) {
          <div class="grid grid-cols-2 gap-4 mb-3">
            <div>
              @if (c.strengths?.length) {
                <div class="text-xs uppercase tracking-wider text-green-400 mb-1">{{ I18N.critique.strengths | translate }}</div>
                <ul class="text-sm space-y-0.5">
                  @for (s of c.strengths; track s.metric_key) {
                    <li class="flex items-center gap-1.5">
                      <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-green-400 shrink-0">check_circle</mat-icon>
                      {{ 'critique.metrics.' + s.metric_key | translate }} ({{ s.value }})
                    </li>
                  }
                </ul>
              }
            </div>
            <div>
              @if (c.weaknesses?.length) {
                <div class="text-xs uppercase tracking-wider text-red-400 mb-1">{{ I18N.critique.weaknesses | translate }}</div>
                <ul class="text-sm space-y-0.5">
                  @for (w of c.weaknesses; track w.metric_key) {
                    <li class="flex items-center gap-1.5">
                      <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-red-400 shrink-0">warning</mat-icon>
                      {{ 'critique.metrics.' + w.metric_key | translate }} ({{ w.value }})
                    </li>
                  }
                </ul>
              }
            </div>
          </div>
        }

        <!-- Detected distortions (advisory, zero-shot) -->
        @if (c.distortions?.length) {
          <div class="mb-3">
            <div class="text-xs uppercase tracking-wider text-amber-400 mb-1">{{ I18N.critique.distortions | translate }}</div>
            <div class="flex flex-wrap gap-1.5">
              @for (d of c.distortions; track d) {
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-amber-400/10 text-amber-400">
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
            <div class="text-xs uppercase tracking-wider opacity-50 mb-1">{{ I18N.critique.suggestions | translate }}</div>
            <ul class="text-sm space-y-0.5">
              @for (tip of c.suggestions; track tip) {
                <li class="flex items-center gap-1.5">
                  <mat-icon class="!text-sm !w-4 !h-4 !leading-4 text-blue-400 shrink-0">lightbulb</mat-icon>
                  {{ 'critique.suggestion.' + tip | translate }}
                </li>
              }
            </ul>
          </div>
        }

        <!-- VLM Critique -->
        @if (c.vlm_critique) {
          @if (c.vlm_source === 'cached') {
            <p class="text-xs opacity-60">{{ I18N.critique.cached_commentary | translate }}</p>
          }
          <div class="mt-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
            <div class="flex items-center mb-1">
              <div class="flex-1 text-xs uppercase tracking-wider opacity-50">{{ I18N.critique.vlm_title | translate }}</div>
              @if (vlmRefreshing()) {
                <mat-spinner diameter="16" [attr.aria-label]="I18N.ui.labels.loading | translate" />
              } @else {
                <button mat-icon-button class="!w-6 !h-6 !p-0 opacity-50 hover:opacity-90"
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

        <!-- Penalties -->
        @if (hasPenalties()) {
          <div class="mt-3 text-xs opacity-60">
            <span class="uppercase tracking-wider">{{ I18N.critique.advisories | translate }}:</span>
            @if (c.penalties.blink) { <span class="ml-2 text-red-400">{{ I18N.critique.penalty.blink | translate }}</span> }
            @if (skinTone(); as st) { <span class="ml-2 text-amber-400">{{ I18N.critique.penalty.skin_tone | translate:{ cast: ('critique.skin_cast.' + st.cast | translate), delta: '' + st.delta } }}</span> }
          </div>
        }
      }
    </mat-dialog-content>
  `,
})
export class PhotoCritiqueDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly storedEdge = STORED_EDGE;
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snack = inject(MatSnackBar);
  protected readonly data = inject<{ photoPath: string; vlmAvailable: boolean }>(MAT_DIALOG_DATA);

  protected readonly loading = signal(true);
  protected readonly critique = signal<CritiqueResponse | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly showRejected = signal(false);
  protected readonly overlayOn = signal(false);
  protected readonly faceMarkers = signal<FaceMarker[]>([]);
  protected readonly overlaySupported = computed(() => this.auth.hasFeature('show_saliency_overlay'));
  protected readonly overlayUrl = computed(
    () => `/api/saliency_overlay?path=${encodeURIComponent(this.data.photoPath)}`,
  );

  protected async toggleOverlay(): Promise<void> {
    const next = !this.overlayOn();
    this.overlayOn.set(next);
    if (next && this.faceMarkers().length === 0) {
      try {
        const res = await firstValueFrom(
          this.api.get<{ faces: FaceMarker[] }>('/photo/face_markers', { path: this.data.photoPath }),
        );
        this.faceMarkers.set(res.faces ?? []);
      } catch {
        // Face boxes are an optional embellishment; the heatmap still shows.
      }
    }
  }

  protected onOverlayError(): void {
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

  async ngOnInit(): Promise<void> {
    try {
      const mode = this.data.vlmAvailable ? 'vlm' : 'rule';
      const res = await firstValueFrom(
        this.api.get<CritiqueResponse>('/critique', {
          path: this.data.photoPath, mode, lang: this.i18n.locale(),
        }),
      );
      this.critique.set(res);
      // GET only reads the stored text; an edition user with nothing stored generates it here
      // (the dialog keeps its loading spinner meanwhile, as it did when GET generated).
      if (mode === 'vlm' && !res.vlm_critique && res.vlm_available) {
        await this.requestVlm(false);
      } else if (mode === 'vlm' && res.vlm_translation_missing && this.auth.isEdition()) {
        // A stored critique with no translation in this locale: the POST translates and
        // stores the cached text without regenerating it.
        await this.requestVlm(false);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : this.i18n.t(I18N.critique.error_fallback);
      this.error.set(message);
    } finally {
      this.loading.set(false);
    }
  }

  protected async refreshVlm(): Promise<void> {
    await this.requestVlm(true);
  }

  private async requestVlm(refresh: boolean): Promise<void> {
    if (this.vlmRefreshing()) return;
    this.vlmRefreshing.set(true);
    try {
      const res = await firstValueFrom(
        this.api.post<CritiqueResponse>('/critique/vlm', {
          path: this.data.photoPath, lang: this.i18n.locale(), refresh,
        }),
      );
      this.critique.set(res);
    } catch {
      // Keep the previous critique visible when generation fails.
    } finally {
      this.vlmRefreshing.set(false);
    }
  }
}
