import { Component, inject, signal, computed, effect, viewChild, TemplateRef, OnInit, OnDestroy, ChangeDetectionStrategy, DestroyRef } from '@angular/core';
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
import { AuthService } from '../../core/services/auth.service';
import { LatestRequest } from '../../shared/utils/latest-request';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from '../gallery/gallery.store';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { MOBILE_DOCKED_BAR_ROW } from '../../shared/utils/mobile-bar';
import type { MergeSuggestionsResponse } from '../../core/api/types';

type MergeSuggestion = MergeSuggestionsResponse['suggestions'][number];
type SuggestionPerson = MergeSuggestion['person1'];

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
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="px-4 pt-4 pb-20 w-full">
      <h1 class="sr-only">{{ I18N.merge_suggestions.title | translate }}</h1>
      <!-- Toolbar projects into the global header on lg+ (HeaderSlotService); on small
           screens it renders as a fixed bottom bar (same #mergeToolbar template). -->
      <div class="lg:hidden">
        <ng-container [ngTemplateOutlet]="mergeToolbar" />
      </div>
      <ng-template #mergeToolbar>
        <div [class]="MOBILE_DOCKED_BAR_ROW" class="flex items-center lg:gap-3 lg:flex-wrap
                    max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-50
                    max-lg:bg-[var(--mat-sys-surface-container)]
                    max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)] safe-area-pb">
          <a mat-icon-button routerLink="/persons" [matTooltip]="I18N.photo_detail.back | translate" [attr.aria-label]="I18N.photo_detail.back | translate">
            <mat-icon>arrow_back</mat-icon>
          </a>
          <span class="text-sm text-[var(--mat-sys-on-surface-variant)] shrink-0">{{ I18N.persons.similarity_threshold | translate }}</span>
          @if (sliderValue(); as value) {
            <mat-slider [min]="0.3" [max]="0.9" [step]="0.05" [discrete]="true" class="w-40">
              <input
                matSliderThumb
                [value]="value"
                (valueChange)="onThresholdChange($event)"
                [attr.aria-label]="I18N.persons.similarity_threshold | translate"
              />
            </mat-slider>
            <span class="text-sm font-mono w-12">{{ value * 100 | fixed:0 }}%</span>
          }
          <div class="flex-1"></div>
          @if (canEdit() && suggestions().length > 0) {
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
          <mat-spinner diameter="48" [attr.aria-label]="I18N.ui.labels.loading | translate" />
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
                  [disabled]="merging() || !canEdit()"
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
                  <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">
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
                  [disabled]="merging() || !canEdit()"
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
                  <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">
                    {{ I18N.persons.face_count | translate:{ count: suggestion.person2.face_count } }}
                  </p>
                </button>
              </div>

              <!-- Dismiss -->
              <div class="flex items-center justify-center pt-2 border-t border-white/10">
                <button
                  mat-icon-button
                  [disabled]="merging() || !canEdit()"
                  [matTooltip]="I18N.common.dismiss | translate"
                  [attr.aria-label]="I18N.common.dismiss | translate"
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
        <div class="text-center py-16 text-[var(--mat-sys-on-surface-variant)]">
          <mat-icon class="!text-5xl !w-12 !h-12 mb-4">check_circle</mat-icon>
          <p>{{ I18N.persons.no_suggestions | translate }}</p>
        </div>
      }
    </div>
  `,
})
export class MergeSuggestionsComponent implements OnInit, OnDestroy {
  protected readonly I18N = i18nKeys();
  protected readonly MOBILE_DOCKED_BAR_ROW = MOBILE_DOCKED_BAR_ROW;
  private readonly api = inject(ApiService);
  private readonly journal = inject(UserActivityJournal);
  /** Merge, reject and accept-all call edition-only routes. */
  protected readonly canEdit = inject(AuthService).isEdition;
  private readonly i18n = inject(I18nService);
  private readonly store = inject(GalleryStore);
  private readonly faceBoxes = inject(PersonFaceBoxesService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private readonly headerSlot = inject(HeaderSlotService);
  private readonly mergeToolbar = viewChild<TemplateRef<unknown>>('mergeToolbar');

  readonly suggestions = signal<MergeSuggestion[]>([]);
  /** Bumped whenever the list is replaced wholesale: an in-flight rollback may
   *  only touch the list it was taken from, never a newer threshold's. */
  private suggestionsVersion = 0;
  private readonly destroyRef = inject(DestroyRef);
  private readonly latestSuggestions = new LatestRequest(this.destroyRef);
  readonly loading = signal(false);
  readonly merging = signal(false);
  /** Null until the server reports the active model's default (or the user picks one). */
  readonly threshold = signal<number | null>(null);
  /** What the slider shows: the user's pick or the server's last answer, else the active
   *  model's default from /api/config, so it renders before the first response (null when
   *  the server did not report one: hidden until the response, never a client constant). */
  readonly sliderValue = computed(() => this.threshold() ?? this.store.config()?.face_merge_threshold ?? null);
  /** Sent only once the user has moved the slider; before that the server decides. */
  private userThreshold: number | null = null;

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
    this.userThreshold = value;
    this.threshold.set(value);
    if (this.thresholdTimeout) clearTimeout(this.thresholdTimeout);
    this.thresholdTimeout = setTimeout(() => this.loadSuggestions(), 300);
  }

  private async loadSuggestions(): Promise<void> {
    // The slider debounces at 300ms, but a slow /merge_suggestions response can
    // still be in flight when the next one starts: only the newest request may
    // write, or the list would show an older threshold's suggestions while the
    // slider reads something else.
    const handle = this.latestSuggestions.begin();
    this.loading.set(true);
    try {
      const res = await firstValueFrom(handle.bind(
        this.api.get<MergeSuggestionsResponse>(
          '/merge_suggestions',
          this.userThreshold === null ? {} : { threshold: this.userThreshold },
        ),
      ));
      if (!handle.isCurrent()) return;
      this.suggestions.set(res.suggestions);
      this.suggestionsVersion++;
      if (this.userThreshold === null) this.threshold.set(res.threshold);
    } catch {
      if (!handle.isCurrent()) return;
      this.snackBar.open(this.i18n.t(I18N.persons.error_loading), '', { duration: 3000 });
    } finally {
      if (handle.isCurrent()) this.loading.set(false);
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
      this.faceBoxes.clear();

      this.journal.record('person', [], { action: 'merge', count: 1, pairs: [[sourceId, target.id]] });
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
    // analyzer stops re-proposing this pair on reload. A failed request puts
    // the entry back where it was: the user must not believe a pair was
    // rejected when the server never heard about it.
    const index = this.suggestions().indexOf(suggestion);
    const version = this.suggestionsVersion;
    this.removeSuggestion(suggestion);
    try {
      await firstValueFrom(
        this.api.post('/persons/merge_suggestions/reject', {
          person1_id: suggestion.person1.id,
          person2_id: suggestion.person2.id,
        }),
      );
    } catch {
      // But only into that same list: a threshold change (or an accept-all)
      // may have replaced it while the request was in flight, and re-inserting
      // a pair the newer list filtered out would let Accept all submit it.
      if (this.suggestionsVersion === version) {
        this.suggestions.update((list) => {
          const restored = [...list];
          restored.splice(Math.min(index, restored.length), 0, suggestion);
          return restored;
        });
      }
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
    }
  }

  async confirmAcceptAll(): Promise<void> {
    const pending = this.suggestions();
    if (pending.length === 0) return;

    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.persons.confirm_merge_title),
        message: this.i18n.t(I18N.persons.confirm_merge_all_message, { count: pending.length }),
      },
    });

    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;
    // The confirmation covered the pairs on screen when the dialog opened. If
    // any of them moved while it was up — a failed rejection rolling its pair
    // back, a single merge or rejection — ask again rather than submit more
    // than was shown.
    if (this.suggestions() !== pending) return this.confirmAcceptAll();
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

      const res = await firstValueFrom(this.api.post<{ merged_count: number }>('/persons/merge_batch', { merges }));
      this.faceBoxes.clear();
      if (res.merged_count > 0) {
        // Never `partial`: the endpoint is one transaction (a failure throws), and it folds overlapping pairs into fewer merges.
        this.journal.record('person', [], { action: 'merge', count: res.merged_count });
      }

      const count = this.suggestions().length;
      this.suggestions.set([]);
      this.suggestionsVersion++;
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
