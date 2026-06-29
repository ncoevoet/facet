import { Component, inject, signal, computed, effect, viewChild, TemplateRef, OnInit, OnDestroy } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatSliderModule } from '@angular/material/slider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { I18N } from '../../core/i18n/keys';

interface SuggestionPerson {
  id: number;
  name: string | null;
  face_count: number;
  face_thumbnail?: boolean;
}

interface MergeSuggestion {
  person1: SuggestionPerson;
  person2: SuggestionPerson;
  similarity: number;
}

interface MergeSuggestionsResponse {
  suggestions: MergeSuggestion[];
}

@Component({
  selector: 'app-merge-suggestions',
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatSliderModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    MatDialogModule,
    MatSnackBarModule,
    TranslatePipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
    NgTemplateOutlet,
  ],
  template: `
    <div class="p-4 md:p-6 pb-20 w-full lg:max-w-[96%] mx-auto">
      <!-- Toolbar projects into the global header on lg+ (HeaderSlotService); on small
           screens it renders as a fixed bottom bar (same #mergeToolbar template). -->
      <div class="lg:hidden">
        <ng-container [ngTemplateOutlet]="mergeToolbar" />
      </div>
      <ng-template #mergeToolbar>
        <div class="flex items-center gap-3 lg:flex-wrap
                    max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-50
                    max-lg:px-4 max-lg:py-2 max-lg:bg-[var(--mat-sys-surface-container)]
                    max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)] safe-area-pb">
          <a mat-icon-button routerLink="/persons" [matTooltip]="I18N.photo_detail.back | translate">
            <mat-icon>arrow_back</mat-icon>
          </a>
          <span class="text-sm opacity-70 shrink-0">{{ I18N.persons.similarity_threshold | translate }}</span>
          <mat-slider [min]="0.3" [max]="0.9" [step]="0.05" [discrete]="true" class="w-40">
            <input
              matSliderThumb
              [value]="threshold()"
              (valueChange)="onThresholdChange($event)"
              [attr.aria-label]="I18N.persons.similarity_threshold | translate"
            />
          </mat-slider>
          <span class="text-sm font-mono w-12">{{ threshold() * 100 | fixed:0 }}%</span>
          <div class="flex-1"></div>
          @if (suggestions().length > 0) {
            <button mat-flat-button [disabled]="merging()" (click)="confirmAcceptAll()">
              <mat-icon>done_all</mat-icon>
              {{ I18N.persons.accept_all | translate:{ count: suggestions().length } }}
            </button>
          }
        </div>
      </ng-template>

      <!-- Loading -->
      @if (loading()) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" />
        </div>
      }

      <!-- Suggestions grid -->
      @if (!loading()) {
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          @for (suggestion of suggestions(); track suggestion.person1.id + '-' + suggestion.person2.id) {
            <mat-card class="!p-4 flex flex-col gap-4">
              <div class="flex items-start justify-between gap-2">
                <!-- Person 1 (click merges the pair into this person) -->
                <button
                  type="button"
                  class="flex-1 min-w-0 flex flex-col items-center gap-2 p-0 bg-transparent border-0 cursor-pointer group disabled:cursor-default"
                  [disabled]="merging()"
                  [matTooltip]="I18N.persons.merge_into_this | translate"
                  (click)="mergeInto(suggestion, suggestion.person1)"
                >
                  <div class="relative w-full aspect-[4/3] rounded-xl bg-[var(--mat-sys-surface-container)] overflow-hidden">
                    <img
                      [src]="suggestion.person1.id | personThumbnailUrl"
                      class="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      [alt]="suggestion.person1.name || (I18N.persons.unnamed | translate)"
                    />
                  </div>
                  <p class="font-medium text-sm text-center truncate w-full">
                    {{ suggestion.person1.name || (I18N.persons.unnamed | translate) }}
                  </p>
                  <p class="text-xs opacity-60">
                    {{ I18N.persons.face_count | translate:{ count: suggestion.person1.face_count } }}
                  </p>
                </button>

                <!-- Similarity badge -->
                <div
                  class="shrink-0 self-center flex items-center justify-center w-12 h-12 rounded-full text-sm font-bold"
                  [matTooltip]="I18N.persons.similarity_match_hint | translate"
                  [class.bg-green-900]="suggestion.similarity >= 0.8"
                  [class.bg-yellow-900]="suggestion.similarity >= 0.6 && suggestion.similarity < 0.8"
                  [class.bg-orange-900]="suggestion.similarity < 0.6"
                >
                  {{ suggestion.similarity * 100 | fixed:0 }}%
                </div>

                <!-- Person 2 (click merges the pair into this person) -->
                <button
                  type="button"
                  class="flex-1 min-w-0 flex flex-col items-center gap-2 p-0 bg-transparent border-0 cursor-pointer group disabled:cursor-default"
                  [disabled]="merging()"
                  [matTooltip]="I18N.persons.merge_into_this | translate"
                  (click)="mergeInto(suggestion, suggestion.person2)"
                >
                  <div class="relative w-full aspect-[4/3] rounded-xl bg-[var(--mat-sys-surface-container)] overflow-hidden">
                    <img
                      [src]="suggestion.person2.id | personThumbnailUrl"
                      class="absolute inset-0 w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      [alt]="suggestion.person2.name || (I18N.persons.unnamed | translate)"
                    />
                  </div>
                  <p class="font-medium text-sm text-center truncate w-full">
                    {{ suggestion.person2.name || (I18N.persons.unnamed | translate) }}
                  </p>
                  <p class="text-xs opacity-60">
                    {{ I18N.persons.face_count | translate:{ count: suggestion.person2.face_count } }}
                  </p>
                </button>
              </div>

              <!-- Dismiss -->
              <div class="flex items-center justify-center pt-2 border-t border-white/10">
                <button
                  mat-icon-button
                  [disabled]="merging()"
                  [matTooltip]="I18N.common.dismiss | translate"
                  (click)="rejectSuggestion(suggestion)"
                >
                  <mat-icon>close</mat-icon>
                </button>
              </div>
            </mat-card>
          }
        </div>
      }

      <!-- Empty state -->
      @if (!loading() && suggestions().length === 0) {
        <div class="text-center py-16 opacity-50">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">check_circle</mat-icon>
          <p>{{ I18N.persons.no_suggestions | translate }}</p>
        </div>
      }
    </div>
  `,
})
export class MergeSuggestionsComponent implements OnInit, OnDestroy {
  protected readonly I18N = I18N;
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly mergeToolbar = viewChild<TemplateRef<unknown>>('mergeToolbar');

  readonly suggestions = signal<MergeSuggestion[]>([]);
  readonly loading = signal(false);
  readonly merging = signal(false);
  readonly threshold = signal(0.6);

  private thresholdTimeout: ReturnType<typeof setTimeout> | null = null;

  readonly hasSuggestions = computed(() => this.suggestions().length > 0);

  constructor() {
    // Project the toolbar into the global header on lg+ (the page renders it in its
    // own bottom bar on small screens — see the #mergeToolbar template).
    effect(() => {
      const tpl = this.mergeToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
  }

  async ngOnInit(): Promise<void> {
    await this.loadSuggestions();
  }

  ngOnDestroy(): void {
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    const tpl = this.mergeToolbar();
    if (tpl) this.headerSlot.clear(tpl);
  }

  onThresholdChange(value: number): void {
    this.threshold.set(value);
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    this.thresholdTimeout = setTimeout(() => this.loadSuggestions(), 300);
  }

  private async loadSuggestions(): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<MergeSuggestionsResponse>('/merge_suggestions', {
          threshold: this.threshold(),
        }),
      );
      this.suggestions.set(res.suggestions);
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.error_loading), '', { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  async mergeInto(suggestion: MergeSuggestion, target: SuggestionPerson): Promise<void> {
    if (this.merging()) return;
    this.merging.set(true);
    try {
      const sourceId = target.id === suggestion.person1.id
        ? suggestion.person2.id
        : suggestion.person1.id;

      await firstValueFrom(
        this.api.post('/persons/merge', { source_id: sourceId, target_id: target.id }),
      );

      this.removeSuggestion(suggestion);
      this.snackBar.open(this.i18n.t(I18N.persons.merged), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
    } finally {
      this.merging.set(false);
    }
  }

  async rejectSuggestion(suggestion: MergeSuggestion): Promise<void> {
    // Optimistically remove from the list, then persist the rejection so the
    // analyzer stops re-proposing this pair on reload.
    this.removeSuggestion(suggestion);
    try {
      await firstValueFrom(
        this.api.post('/persons/merge_suggestions/reject', {
          person1_id: suggestion.person1.id,
          person2_id: suggestion.person2.id,
        }),
      );
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
    }
  }

  async confirmAcceptAll(): Promise<void> {
    const count = this.suggestions().length;
    if (count === 0) return;

    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.persons.confirm_merge_title),
        message: this.i18n.t(I18N.persons.confirm_merge_all_message, { count }),
      },
    });

    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;

    await this.acceptAll();
  }

  async acceptAll(): Promise<void> {
    this.merging.set(true);
    try {
      const merges = this.suggestions().map((s) => {
        const [source, target] =
          s.person1.face_count >= s.person2.face_count
            ? [s.person2, s.person1]
            : [s.person1, s.person2];
        return { source_id: source.id, target_id: target.id };
      });

      await firstValueFrom(this.api.post('/persons/merge_batch', { merges }));

      const count = this.suggestions().length;
      this.suggestions.set([]);
      this.snackBar.open(this.i18n.t(I18N.persons.batch_merged, { count }), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t(I18N.persons.merge_error), '', { duration: 3000 });
    } finally {
      this.merging.set(false);
    }
  }

  private removeSuggestion(suggestion: MergeSuggestion): void {
    this.suggestions.update((list) =>
      list.filter(
        (s) =>
          !(s.person1.id === suggestion.person1.id && s.person2.id === suggestion.person2.id),
      ),
    );
  }
}
