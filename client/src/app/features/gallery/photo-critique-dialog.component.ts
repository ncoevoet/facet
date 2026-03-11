import { Component, Pipe, PipeTransform, inject, signal, computed, OnInit } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';
import { MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

interface CritiqueBreakdown {
  metric: string;
  metric_key: string;
  value: number;
  weight: number;
  contribution: number;
}

interface CritiqueMetricRef {
  metric_key: string;
  value: number;
}

interface CategoryReasonDetail {
  key: string;
  value?: number;
  threshold?: number;
  tags?: string[];
}

interface CategoryReason {
  reason_key: string;
  category: string;
  details: CategoryReasonDetail[];
}

interface CritiqueResponse {
  category: string;
  category_reason: CategoryReason;
  aggregate: number;
  breakdown: CritiqueBreakdown[];
  strengths: CritiqueMetricRef[];
  weaknesses: CritiqueMetricRef[];
  suggestions: string[];
  penalties: Record<string, number | boolean>;
  vlm_critique?: string;
  vlm_available?: boolean;
}

@Pipe({ name: 'contributionColor', standalone: true, pure: true })
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
    if (reason.reason_key === 'default') {
      return this.i18n.t('critique.reason.default');
    }
    if (reason.details.length === 0) {
      return this.i18n.t('critique.reason.matched_generic');
    }
    const details = reason.details.map(d => {
      if (d.key === 'tags') {
        return this.i18n.t('critique.reason.tags', { tags: d.tags!.join(', ') });
      }
      return this.i18n.t(`critique.reason.${d.key}`, {
        value: d.value ?? '',
        threshold: d.threshold ?? '',
      });
    });
    return `${this.i18n.t('critique.reason.classified_as', { category: reason.category })}: ${details.join('; ')}`;
  }
}

@Component({
  selector: 'app-photo-critique-dialog',
  standalone: true,
  imports: [
    MatDialogModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule,
    DecimalPipe, PercentPipe, TranslatePipe, ContributionColorPipe, CategoryReasonPipe,
  ],
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2">
      <mat-icon>analytics</mat-icon>
      <span class="flex-1">{{ 'critique.title' | translate }}</span>
      <button mat-icon-button mat-dialog-close class="shrink-0 !-mt-1 !-mr-2">
        <mat-icon>close</mat-icon>
      </button>
    </h2>
    <mat-dialog-content class="!max-h-[70vh]">
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" />
        </div>
      } @else if (error(); as e) {
        <div class="flex flex-col items-center gap-2 py-8 text-red-400">
          <mat-icon class="!text-4xl !w-10 !h-10">error_outline</mat-icon>
          <p class="text-sm">{{ e }}</p>
        </div>
      } @else if (critique(); as c) {
        <!-- Category reason -->
        <div class="text-sm mb-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
          <div class="text-xs uppercase tracking-wider opacity-50 mb-1">{{ 'critique.category_reason' | translate }}</div>
          {{ c.category_reason | categoryReason }}
        </div>

        <!-- Score breakdown table -->
        <div class="text-xs uppercase tracking-wider opacity-50 mb-2">{{ 'critique.breakdown' | translate }}</div>
        <table class="w-full text-sm mb-4">
          <thead>
            <tr class="border-b border-[var(--mat-sys-outline-variant)]">
              <th class="text-left py-1 font-medium">{{ 'critique.metric' | translate }}</th>
              <th class="text-right py-1 font-medium w-16">{{ 'critique.value' | translate }}</th>
              <th class="text-right py-1 font-medium w-20">{{ 'critique.weight' | translate }}</th>
              <th class="text-right py-1 font-medium w-28">{{ 'critique.contribution_label' | translate }}</th>
            </tr>
          </thead>
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
        </table>

        <!-- Strengths & Weaknesses side by side -->
        @if (c.strengths.length || c.weaknesses.length) {
          <div class="grid grid-cols-2 gap-4 mb-3">
            <div>
              @if (c.strengths.length) {
                <div class="text-xs uppercase tracking-wider text-green-400 mb-1">{{ 'critique.strengths' | translate }}</div>
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
              @if (c.weaknesses.length) {
                <div class="text-xs uppercase tracking-wider text-red-400 mb-1">{{ 'critique.weaknesses' | translate }}</div>
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

        <!-- Suggestions -->
        @if (c.suggestions.length) {
          <div class="mb-3">
            <div class="text-xs uppercase tracking-wider opacity-50 mb-1">{{ 'critique.suggestions' | translate }}</div>
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
          <div class="mt-4 p-3 rounded-lg bg-[var(--mat-sys-surface-container)]">
            <div class="text-xs uppercase tracking-wider opacity-50 mb-1">{{ 'critique.vlm_title' | translate }}</div>
            <p class="text-sm">{{ c.vlm_critique }}</p>
          </div>
        }

        <!-- Penalties -->
        @if (hasPenalties()) {
          <div class="mt-3 text-xs opacity-60">
            <span class="uppercase tracking-wider">{{ 'critique.penalties' | translate }}:</span>
            @if (c.penalties['blink']) { <span class="ml-2 text-red-400">{{ 'critique.penalty.blink' | translate }}</span> }
            @if (c.penalties['noise']) { <span class="ml-2">{{ 'critique.penalty.noise' | translate:{ value: '' + c.penalties['noise'] } }}</span> }
            @if (c.penalties['highlight_clipping']) { <span class="ml-2">{{ 'critique.penalty.highlight_clipping' | translate:{ value: '' + c.penalties['highlight_clipping'] } }}</span> }
            @if (c.penalties['shadow_clipping']) { <span class="ml-2">{{ 'critique.penalty.shadow_clipping' | translate:{ value: '' + c.penalties['shadow_clipping'] } }}</span> }
          </div>
        }
      }
    </mat-dialog-content>
  `,
})
export class PhotoCritiqueDialogComponent implements OnInit {
  private api = inject(ApiService);
  private i18n = inject(I18nService);
  private data = inject<{ photoPath: string; vlmAvailable: boolean }>(MAT_DIALOG_DATA);

  protected readonly loading = signal(true);
  protected readonly critique = signal<CritiqueResponse | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly hasPenalties = computed(() => {
    const c = this.critique();
    return !!(c && Object.keys(c.penalties).length > 0);
  });

  async ngOnInit(): Promise<void> {
    try {
      const mode = this.data.vlmAvailable ? 'vlm' : 'rule';
      const res = await firstValueFrom(
        this.api.get<CritiqueResponse>('/critique', { path: this.data.photoPath, mode }),
      );
      this.critique.set(res);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : this.i18n.t('critique.error_fallback');
      this.error.set(message);
    } finally {
      this.loading.set(false);
    }
  }
}
