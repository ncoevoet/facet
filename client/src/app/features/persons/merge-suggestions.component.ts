import { Component, inject, signal, computed, OnInit, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatSliderModule } from '@angular/material/slider';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { MergeTargetDialogComponent } from './manage-persons.component';
import { Person } from '../../shared/components/person-card/person-card.component';

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
    MatDialogModule,
    MatSnackBarModule,
    TranslatePipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
  ],
  template: `
    <div class="p-4 md:p-6 max-w-screen-xl mx-auto">
      <!-- Header -->
      <div class="flex flex-wrap items-center gap-4 mb-6">
        <a mat-icon-button routerLink="/persons">
          <mat-icon>arrow_back</mat-icon>
        </a>
        <h1 class="text-2xl font-medium">{{ 'persons.merge_suggestions_title' | translate }}</h1>
        <div class="flex-1"></div>
        @if (suggestions().length > 0) {
          <button mat-flat-button [disabled]="merging()" (click)="acceptAll()">
            <mat-icon>done_all</mat-icon>
            {{ 'persons.accept_all' | translate:{ count: suggestions().length } }}
          </button>
        }
      </div>

      <!-- Threshold control -->
      <div class="flex items-center gap-3 mb-6">
        <span class="text-sm text-gray-400 shrink-0">{{ 'persons.similarity_threshold' | translate }}</span>
        <mat-slider [min]="0.3" [max]="0.9" [step]="0.05" [discrete]="true" class="flex-1 max-w-xs">
          <input matSliderThumb [value]="threshold()" (valueChange)="onThresholdChange($event)" />
        </mat-slider>
        <span class="text-sm font-mono w-12">{{ threshold() * 100 | fixed:0 }}%</span>
      </div>

      <!-- Loading -->
      @if (loading()) {
        <div class="flex justify-center py-16">
          <mat-spinner diameter="48" />
        </div>
      }

      <!-- Suggestions list -->
      <div class="flex flex-col gap-4">
        @for (suggestion of suggestions(); track suggestion.person1.id + '-' + suggestion.person2.id) {
          <mat-card class="!p-0">
            <div class="flex flex-col sm:flex-row items-stretch">
              <!-- Person 1 -->
              <div class="flex-1 flex items-center gap-3 p-4">
                <img
                  [src]="suggestion.person1.id | personThumbnailUrl"
                  class="w-16 h-16 rounded-full object-cover shrink-0"
                  alt=""
                />
                <div class="min-w-0">
                  <p class="font-medium truncate">
                    {{ suggestion.person1.name || ('persons.unnamed' | translate) }}
                  </p>
                  <p class="text-sm opacity-60">
                    {{ 'persons.face_count' | translate:{ count: suggestion.person1.face_count } }}
                  </p>
                </div>
              </div>

              <!-- Similarity badge -->
              <div class="flex items-center justify-center px-4 py-2 sm:py-4">
                <div
                  class="flex flex-col items-center gap-1 px-4 py-2 rounded-full"
                  [class.bg-green-900]="suggestion.similarity >= 0.8"
                  [class.bg-yellow-900]="suggestion.similarity >= 0.6 && suggestion.similarity < 0.8"
                  [class.bg-orange-900]="suggestion.similarity < 0.6"
                >
                  <mat-icon class="!text-lg">compare_arrows</mat-icon>
                  <span class="text-sm font-bold">
                    {{ suggestion.similarity * 100 | fixed:0 }}%
                  </span>
                </div>
              </div>

              <!-- Person 2 -->
              <div class="flex-1 flex items-center gap-3 p-4">
                <img
                  [src]="suggestion.person2.id | personThumbnailUrl"
                  class="w-16 h-16 rounded-full object-cover shrink-0"
                  alt=""
                />
                <div class="min-w-0">
                  <p class="font-medium truncate">
                    {{ suggestion.person2.name || ('persons.unnamed' | translate) }}
                  </p>
                  <p class="text-sm opacity-60">
                    {{ 'persons.face_count' | translate:{ count: suggestion.person2.face_count } }}
                  </p>
                </div>
              </div>

              <!-- Actions -->
              <div class="flex items-center gap-2 p-4 sm:border-l sm:border-white/10">
                <button
                  mat-flat-button
                  [disabled]="merging()"
                  (click)="acceptSuggestion(suggestion)"
                >
                  <mat-icon>merge</mat-icon>
                  {{ 'persons.accept' | translate }}
                </button>
                <button
                  mat-icon-button
                  [disabled]="merging()"
                  (click)="rejectSuggestion(suggestion)"
                >
                  <mat-icon>close</mat-icon>
                </button>
              </div>
            </div>
          </mat-card>
        }
      </div>

      <!-- Empty state -->
      @if (!loading() && suggestions().length === 0) {
        <div class="text-center py-16 opacity-50">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">check_circle</mat-icon>
          <p>{{ 'persons.no_suggestions' | translate }}</p>
        </div>
      }
    </div>
  `,
})
export class MergeSuggestionsComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  readonly suggestions = signal<MergeSuggestion[]>([]);
  readonly loading = signal(false);
  readonly merging = signal(false);
  readonly threshold = signal(0.6);

  private thresholdTimeout: ReturnType<typeof setTimeout> | null = null;

  readonly hasSuggestions = computed(() => this.suggestions().length > 0);

  async ngOnInit(): Promise<void> {
    await this.loadSuggestions();
  }

  ngOnDestroy(): void {
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
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
      this.snackBar.open(this.i18n.t('persons.error_loading'), '', { duration: 3000 });
    } finally {
      this.loading.set(false);
    }
  }

  async acceptSuggestion(suggestion: MergeSuggestion): Promise<void> {
    const persons: Person[] = [
      { ...suggestion.person1, face_thumbnail: true },
      { ...suggestion.person2, face_thumbnail: true },
    ];

    const ref = this.dialog.open(MergeTargetDialogComponent, {
      data: { persons },
      width: '400px',
    });

    const targetId: number | null = await firstValueFrom(ref.afterClosed());
    if (!targetId) return;

    this.merging.set(true);
    try {
      const sourceId = targetId === suggestion.person1.id
        ? suggestion.person2.id
        : suggestion.person1.id;

      await firstValueFrom(
        this.api.post('/persons/merge', { source_id: sourceId, target_id: targetId }),
      );

      this.removeSuggestion(suggestion);
      this.snackBar.open(this.i18n.t('persons.merged'), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.merge_error'), '', { duration: 3000 });
    } finally {
      this.merging.set(false);
    }
  }

  rejectSuggestion(suggestion: MergeSuggestion): void {
    this.removeSuggestion(suggestion);
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
      this.snackBar.open(this.i18n.t('persons.batch_merged', { count }), '', { duration: 2000 });
    } catch {
      this.snackBar.open(this.i18n.t('persons.merge_error'), '', { duration: 3000 });
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
