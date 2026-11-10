import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, Injector, input, signal, untracked, viewChild } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
import { StalenessGuard, StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { FaceThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { InfiniteScrollDirective } from '../../shared/directives/infinite-scroll.directive';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';

type Face = components['schemas']['FaceReviewItem'];
type Response = components['schemas']['FaceReviewResponse'];
/** `AssignFacesRequest` refuses more than 500 face ids (and tokens) in one call. */
const ASSIGN_FACES_MAX = 500;

interface Choice { personId: number; name: string }
interface CapturedFace extends Choice { faceId: number; token: string }
interface FeedbackReceipt { face: Face; choice: Choice; receiptId: string }
interface ReceiptReason { name: string; label: string; count: number }
interface AssignmentReport { assigned_count: number; already: number[]; missing: number[]; skipped_model: number[]; skipped_hidden: number[]; skipped_assigned: number[]; skipped_changed: number[] }
interface ReviewGroup { id: number; name: string; faces: Face[]; ids: number[]; selectedCount: number }
/** Whatever opened the person chooser and takes focus back when it closes without moving the face. */
interface FocusTarget { focus(): void }

@Component({
  selector: 'app-face-review-queue',
  imports: [MatButtonModule, MatDividerModule, MatIconModule, MatMenuModule, MatProgressSpinnerModule, MatTooltipModule, RouterLink, TranslatePipe, FixedPipe, PluralKeyPipe, FaceThumbnailUrlPipe, PersonThumbnailUrlPipe, ContextHelpComponent, InfiniteScrollDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0', tabindex: '-1', '[class.pb-24]': 'selected().size > 0 || !!pending()' },
  template: `
    <div class="flex flex-wrap items-center gap-2 py-3">
      <div class="min-w-0 flex-1">
        @if (!error()) { <p role="status" class="m-0 text-sm">{{ I18N.persons.review_queue.total | translate:{ count: total() } }}</p> }
      </div>
      <button mat-stroked-button data-queue-reload [disabled]="loading() || busy()" (click)="load(0)"><mat-icon>refresh</mat-icon>{{ I18N.persons.review_queue.reload | translate }}</button>
    </div>
    @if (receipt(); as result) {
      <p #receiptStatus role="status" tabindex="-1" data-assignment-receipt class="text-sm">{{ I18N.persons.review_queue.receipt | translate:{ assigned: result.assigned, skipped: result.skipped } }}</p>
      @if (result.reasons.length) { <details data-receipt-reasons class="mb-3 text-xs"><summary class="min-h-11 cursor-pointer">{{ I18N.persons.review_queue.receipt_details | translate }}</summary><ul class="pl-5">@for (reason of result.reasons; track $index) { <li>{{ reason.name }} · {{ reason.label | translate }}: {{ reason.count }}</li> }</ul></details> }
    }
    @if (feedbackReceipt(); as result) {
      <div role="status" data-feedback-receipt class="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span>{{ I18N.persons.review_queue.feedback_saved | translate:{name: result.choice.name} }}</span>
        <button mat-stroked-button data-feedback-undo [disabled]="interactionLocked()" (click)="undoFeedback()"><mat-icon>undo</mat-icon>{{ I18N.persons.review_queue.feedback_undo | translate }}</button>
      </div>
    }
    @if (error()) {
      <div #queueAlert role="alert" tabindex="-1" class="mb-3 rounded border border-[var(--mat-sys-outline)] p-3 text-sm">
        {{ (uncertain() ? I18N.persons.review_queue.uncertain : changed() ? I18N.persons.review_queue.changed : I18N.persons.review_queue.read_error) | translate }}
        @if (!busy()) { <button mat-stroked-button data-queue-retry (click)="retry()"><mat-icon>refresh</mat-icon>{{ I18N.gallery.load_error.retry | translate }}</button> }
        @if (mode() === 'matches') { <button mat-stroked-button data-browse-without-matches (click)="withoutSuggestions.set(true); load(0)">{{ I18N.persons.review_queue.without_matches | translate }}</button> }
      </div>
    }
    @if (suggestionsSkipped() && !error()) { <p role="status" data-suggestions-skipped class="mb-3 text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.suggestions_skipped | translate }}</p> }
    @if (loading() && !faces().length) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
    @for (group of groups(); track group.id) {
      @let headingId = 'review-group-' + mode() + '-' + group.id;
      @let faceCount = group.faces.length | pluralKey:I18N.persons.review_queue.group_count:I18N.persons.review_queue.group_count_plural | translate:{ count: group.faces.length };
      <section class="mb-4 rounded-xl bg-[var(--mat-sys-surface-container)] p-3 sm:p-4" [attr.data-review-group]="group.id" [attr.aria-labelledby]="group.id || mode() === 'matches' ? headingId : null">
        @if (group.id) {
          <div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span class="h-10 w-10 shrink-0 overflow-hidden rounded-full bg-[var(--mat-sys-surface-container-high)]"><img [src]="group.id | personThumbnailUrl" alt="" class="h-full w-full object-cover" /></span>
            <h3 [id]="headingId" class="m-0 min-w-0 flex-1 break-words text-sm font-medium">{{ group.name }} <span class="font-normal text-[var(--mat-sys-on-surface-variant)]">· {{ faceCount }}</span></h3>
            <label class="flex min-h-11 cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" data-select-group [checked]="group.selectedCount === group.ids.length" [indeterminate]="group.selectedCount > 0 && group.selectedCount < group.ids.length"
                     [disabled]="interactionLocked()" [attr.aria-label]="I18N.persons.review_queue.select_group | translate:{ name: group.name }" (change)="toggleGroup(group, $event)" />
              {{ I18N.gallery.selection.select_all | translate }}
            </label>
          </div>
        } @else if (mode() === 'matches') {
          <h3 [id]="headingId" class="m-0 mb-3 text-sm font-medium">{{ I18N.persons.review_queue.no_suggestion | translate }} <span class="font-normal text-[var(--mat-sys-on-surface-variant)]">· {{ faceCount }}</span></h3>
        }
        <div class="grid grid-cols-3 gap-2 sm:grid-cols-[repeat(auto-fill,minmax(8rem,1fr))]">
          @for (face of group.faces; track face.face_id) {
            @let choice = choices().get(face.face_id);
            @let similarity = faceSimilarity().get(face.face_id);
            @let isSelected = selected().has(face.face_id);
            @let warning = embeddingWarnings[face.embedding_state];
            <div class="relative min-w-0 scroll-mb-28" [attr.data-review-face]="face.face_id">
              <button #tile type="button" data-review-tile
                      class="relative block w-full cursor-pointer overflow-hidden rounded-lg border-2 bg-[var(--mat-sys-surface-container-high)] p-0 focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-[var(--mat-sys-primary)] aria-disabled:cursor-default"
                      [class.border-[var(--mat-sys-primary)]]="isSelected" [class.border-transparent]="!isSelected"
                      [attr.aria-pressed]="choice ? isSelected : null" [attr.aria-disabled]="interactionLocked() ? 'true' : null"
                      [attr.aria-label]="(choice ? (I18N.persons.review_queue.assign_label | translate:{ id: face.face_id, name: choice.name }) : (I18N.persons.review_queue.choose_for | translate:{ id: face.face_id }))
                        + (choice && similarity !== undefined ? '. ' + (I18N.persons.review_queue.similarity_label | translate:{ name: choice.name, value: similarity }) : '')
                        + (warning ? '. ' + (warning | translate) : '')"
                      (click)="activate(face, tile)">
                <img [src]="face.face_id | faceThumbnailUrl" alt="" loading="lazy" class="block aspect-square w-full object-cover" />
                @if (!choice) {
                  <span aria-hidden="true" class="absolute left-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-white"><mat-icon class="!h-4 !w-4 !text-base !leading-4">person_search</mat-icon></span>
                } @else if (isSelected) {
                  <span aria-hidden="true" data-tile-check class="absolute left-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-full bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)]"><mat-icon class="!h-4 !w-4 !text-base !leading-4">check</mat-icon></span>
                }
                @if ((choice && similarity !== undefined) || warning) {
                  <span data-tile-strip class="absolute inset-x-0 bottom-0 flex min-h-6 items-center gap-1 bg-black/60 px-1.5 py-0.5 text-xs text-white">
                    @if (warning) { <mat-icon data-tile-warning aria-hidden="true" class="!h-4 !w-4 !text-base !leading-4" [matTooltip]="warning | translate">warning</mat-icon> }
                    @if (choice && similarity !== undefined) { <span class="ml-auto">{{ I18N.persons.find_more_similarity | translate:{ percent: similarity } }}</span> }
                  </span>
                }
              </button>
              <button mat-icon-button #actions="matMenuTrigger" data-face-actions type="button"
                      class="!absolute right-1 top-1 !h-8 !w-8 !p-1 !bg-black/50 !text-white pointer-coarse:!h-11 pointer-coarse:!w-11 pointer-coarse:!p-2.5"
                      [matMenuTriggerFor]="faceMenu" [matMenuTriggerData]="{ face, actions }" [attr.aria-label]="I18N.persons.review_queue.face_actions | translate:{ id: face.face_id }">
                <mat-icon>more_vert</mat-icon>
              </button>
            </div>
          }
        </div>
      </section>
    }
    <mat-menu #faceMenu="matMenu" xPosition="before">
      <ng-template matMenuContent let-face="face" let-actions="actions">
        @let choice = choices().get(face.face_id);
        <a mat-menu-item data-open-photo routerLink="/photo" [queryParams]="{ path: face.photo_path }" target="_blank" rel="noopener"><mat-icon>open_in_new</mat-icon>{{ I18N.persons.review_queue.open_photo | translate }}</a>
        @if (face.suggestions.length > 1 || (face.suggestions.length && !faceSimilarity().has(face.face_id))) {
          <mat-divider />
          @for (suggestion of face.suggestions; track suggestion.person_id) {
            @let current = choice?.personId === suggestion.person_id;
            <button mat-menu-item role="menuitemradio" data-suggestion [attr.aria-checked]="current" [disabled]="interactionLocked()" (click)="chooseSuggestion(face, suggestion.person_id, suggestion.name)">
              <mat-icon>{{ current ? 'radio_button_checked' : 'radio_button_unchecked' }}</mat-icon>{{ suggestion.name }} · {{ suggestion.similarity * 100 | fixed:0 }}%
            </button>
          }
        }
        <mat-divider />
        <button mat-menu-item data-choose-person [disabled]="interactionLocked()" (click)="chooseOther(face, actions)"><mat-icon>person_search</mat-icon>{{ I18N.persons.review_queue.choose_person | translate }}</button>
        @if (choice) {
          <button mat-menu-item data-not-person [disabled]="interactionLocked()" (click)="rejectSuggestion(face)"><mat-icon>block</mat-icon>{{ I18N.persons.review_queue.not_person | translate:{ name: choice.name } }}</button>
        }
        <button mat-menu-item data-skip-face [disabled]="busy() || !!pending() || choosing()" (click)="skip(face.face_id)"><mat-icon>skip_next</mat-icon>{{ I18N.persons.review_queue.skip | translate }}</button>
      </ng-template>
    </mat-menu>
    @if (!loading() && !error() && !groups().length) { <p class="py-6 text-center text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.empty | translate }}</p> }
    <!-- Next page: the sentinel exists only while a read may start, so it re-fires on its own once a page lands or a lock lifts. -->
    @if (nextAfter() !== null && !error()) {
      <div data-queue-more class="flex flex-col items-center py-8">
        @if (canLoadMore()) { <div appInfiniteScroll data-queue-sentinel class="h-px w-full" (scrollReached)="loadNext()"></div> }
        @if (loading()) { <mat-spinner diameter="36" [attr.aria-label]="I18N.ui.labels.loading | translate" /> }
      </div>
    }
    <app-context-help [label]="I18N.persons.review_queue.about" [keys]="[I18N.persons.review_queue.help]" />
    @if (selected().size || pending()) {
      <div data-review-bar class="fixed inset-x-0 bottom-0 z-50 max-h-[70dvh] overflow-y-auto border-t border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] px-4 py-2 shadow-lg max-lg:bottom-[calc(3rem+1px+env(safe-area-inset-bottom))]">
        @if (pending()) {
          <section #previewPanel tabindex="-1" data-assignment-preview class="mx-auto mb-2 flex max-w-3xl flex-col gap-2 rounded-xl border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container-high)] p-4" (keydown.escape)="cancel($event)">
            <h3 class="m-0 text-sm font-medium">{{ I18N.persons.review_queue.confirm_title | translate }}</h3>
            <ul class="my-2 max-h-48 overflow-y-auto pl-5 text-sm">
              @for (group of planGroups(); track group.personId) { <li>{{ group.name }} · {{ group.count }}</li> }
            </ul>
            <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.confirm_help | translate }}</p>
            <div class="flex justify-end gap-2"><button mat-button [disabled]="busy()" (click)="cancel($event)">{{ I18N.dialog.cancel | translate }}</button><button mat-flat-button data-confirm-assignment [disabled]="busy()" (click)="apply()"><mat-icon>check</mat-icon>{{ I18N.persons.review_queue.confirm | translate }}</button></div>
          </section>
        }
        <div class="flex flex-wrap items-center justify-center gap-2">
          <span data-review-count class="text-sm font-medium">{{ I18N.gallery.selection.count | translate:{ count: selected().size } }}</span>
          <button mat-button data-review-clear [disabled]="interactionLocked()" (click)="clearSelection()"><mat-icon>close</mat-icon>{{ I18N.persons.clear_selection | translate }}</button>
          <button mat-flat-button data-review-selected [disabled]="!selected().size || loading() || busy() || uncertain() || changed() || choosing()" (click)="preview($event)"><mat-icon>fact_check</mat-icon>{{ selected().size | pluralKey:I18N.persons.review_queue.preview:I18N.persons.review_queue.preview_plural | translate:{ count: selected().size } }}</button>
        </div>
      </div>
    }
  `,
})
export class FaceReviewQueueComponent {
  focus(): void { this.host.nativeElement.focus(); }
  protected readonly I18N = I18N;
  /** Why a face cannot be matched, by the state of its embedding. */
  protected readonly embeddingWarnings: Record<Face['embedding_state'], string | null> = {
    ready: null, incompatible: I18N.persons.review_queue.model_mismatch, unavailable: I18N.persons.review_queue.matching_unavailable,
  };
  readonly mode = input.required<'matches' | 'unassigned'>();
  private readonly api = inject(ApiService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private chooser: MatDialogRef<unknown> | null = null;
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly boxes = inject(PersonFaceBoxesService);
  private readonly owner = this.auth.identity();
  private readonly previewPanel = viewChild<ElementRef<HTMLElement>>('previewPanel');
  private readonly receiptStatus = viewChild<ElementRef<HTMLElement>>('receiptStatus');
  private readonly queueAlert = viewChild<ElementRef<HTMLElement>>('queueAlert');
  private generation = 0;
  private resumeAfterNavigation = !!this.router.currentNavigation();
  private readonly navigationPending = trackPendingNavigation({
    started: () => { this.resumeAfterNavigation = true; this.reset(); },
    settled: () => {
      const resume = this.resumeAfterNavigation;
      this.resumeAfterNavigation = false;
      if (resume && this.ownsRoute()) void this.load(0);
    },
  });
  private planGuard: StalenessGuard | null = null;
  private feedbackGuard: StalenessGuard | null = null;
  private returnFocus: HTMLElement | null = null;
  protected readonly faces = signal<Face[]>([]);
  protected readonly total = signal(0);
  protected readonly nextAfter = signal<number | null>(null);
  protected readonly selected = signal(new Set<number>());
  protected readonly choices = signal(new Map<number, Choice>());
  protected readonly loading = signal(false);
  protected readonly busy = signal(false);
  protected readonly choosing = signal(false);
  protected readonly uncertain = signal(false);
  protected readonly changed = signal(false);
  protected readonly error = signal(false);
  /** The user's own "Browse without matches" choice; it stays until the tab is remounted. */
  protected readonly withoutSuggestions = signal(false);
  /** Set by a 412 for the current read only; every fresh first-page read asks for suggestions again. */
  private readonly refusedSuggestions = signal(false);
  private readonly wantsSuggestions = computed(() => this.mode() === 'matches' && !this.withoutSuggestions() && !this.refusedSuggestions());
  protected readonly suggestionsSkipped = signal(false);
  protected readonly pending = signal<readonly CapturedFace[] | null>(null);
  protected readonly interactionLocked = computed(() => this.busy() || !!this.pending() || this.uncertain() || this.changed() || this.choosing());
  protected readonly canLoadMore = computed(() => this.nextAfter() !== null && !this.loading() && !this.error() && !this.interactionLocked());
  /** The cursor of a next page that failed to read, so Retry resumes there instead of dropping the loaded faces. */
  private retryAfter = 0;
  protected readonly receipt = signal<{ assigned: number; skipped: number; reasons: ReceiptReason[] } | null>(null);
  protected readonly feedbackReceipt = signal<FeedbackReceipt | null>(null);
  /** People in face order, then the faces with no person chosen yet. */
  protected readonly groups = computed(() => {
    const selected = this.selected();
    const groups = new Map<number, ReviewGroup>();
    for (const face of this.faces()) {
      const choice = this.choices().get(face.face_id);
      const id = choice?.personId ?? 0;
      const group = groups.get(id) ?? { id, name: choice?.name ?? '', faces: [], ids: [], selectedCount: 0 };
      group.faces.push(face); group.ids.push(face.face_id);
      if (selected.has(face.face_id)) group.selectedCount++;
      groups.set(id, group);
    }
    const unchosen = groups.get(0);
    groups.delete(0);
    return unchosen ? [...groups.values(), unchosen] : [...groups.values()];
  });
  /** Rounded similarity of each face to its current choice, only when that choice is one of its suggestions. */
  protected readonly faceSimilarity = computed(() => {
    const similarity = new Map<number, number>();
    for (const face of this.faces()) {
      const personId = this.choices().get(face.face_id)?.personId;
      const match = face.suggestions.find(suggestion => suggestion.person_id === personId);
      if (match) similarity.set(face.face_id, Math.round(match.similarity * 100));
    }
    return similarity;
  });
  protected readonly planGroups = computed(() => {
    const groups = new Map<number, { personId: number; name: string; count: number }>();
    for (const face of this.pending() ?? []) {
      const group = groups.get(face.personId) ?? { personId: face.personId, name: face.name, count: 0 };
      group.count++; groups.set(face.personId, group);
    }
    return [...groups.values()];
  });

  constructor() {
    effect(() => {
      this.auth.status(); this.auth.isEdition(); this.auth.identity(); this.mode();
      untracked(() => { this.reset(); if (this.allowed()) void this.load(0); });
    });
    this.destroyRef.onDestroy(() => { this.generation++; this.chooser?.close(null); this.planGuard?.dispose(); this.feedbackGuard?.dispose(); });
  }
  private ownsRoute(): boolean {
    const url = this.router.parseUrl(this.router.url);
    const segments = url.root.children['primary']?.segments;
    return segments?.length === 1 && segments[0].path === 'persons' && url.queryParams['tab'] === this.mode();
  }
  reload(): void { void this.load(0); }
  private allowed(): boolean { return !this.destroyRef.destroyed && !this.navigationPending() && this.ownsRoute() && this.auth.isEdition() && this.auth.identity() === this.owner; }
  private capture(): StalenessGuard {
    const token = this.auth.token, generation = this.generation;
    return this.guards.create(this.destroyRef, { track: 'status', valid: () => this.allowed() && this.auth.token === token && this.generation === generation });
  }
  private reset(): void {
    this.generation++; this.planGuard?.dispose(); this.planGuard = null;
    this.feedbackGuard?.dispose(); this.feedbackGuard = null; this.feedbackReceipt.set(null);
    this.chooser?.close(null); this.chooser = null; this.choosing.set(false);
    this.total.set(0); this.error.set(false); this.uncertain.set(false); this.changed.set(false);
    this.pending.set(null); this.faces.set([]); this.selected.set(new Set()); this.choices.set(new Map());
    this.receipt.set(null); this.loading.set(false); this.busy.set(false); this.nextAfter.set(null);
    this.suggestionsSkipped.set(false);
  }
  protected loadNext(): void {
    const after = this.nextAfter();
    if (after !== null && this.canLoadMore()) void this.load(after);
  }
  protected retry(): void {
    void this.load(this.retryAfter && !this.uncertain() && !this.changed() ? this.retryAfter : 0);
  }
  protected async load(after: number, afterRefusal = false): Promise<void> {
    if (!this.allowed() || this.busy() || (after > 0 && (this.loading() || this.pending() || this.uncertain() || this.changed() || this.choosing()))) return;
    if (after === 0) { this.reset(); if (!afterRefusal) this.refusedSuggestions.set(false); }
    this.loading.set(true); this.error.set(false); this.retryAfter = 0;
    const guard = this.capture(), generation = this.generation;
    let retryWithoutSuggestions = false;
    try {
      const response = await firstValueFrom(this.api.get<Response>('/faces/review', { after_id: after, limit: 48, suggest: this.wantsSuggestions() }));
      if (!guard.current()) return;
      const existing = after > 0 ? this.faces() : [];
      const ids = new Set(existing.map(face => face.face_id));
      this.faces.set([...existing, ...response.faces.filter(face => !ids.has(face.face_id))]);
      this.total.set(response.total_unassigned); this.nextAfter.set(response.next_after_id);
      const choices = after > 0 ? new Map(this.choices()) : new Map<number, Choice>();
      for (const face of response.faces) if (!choices.has(face.face_id) && face.suggestions[0]) {
        choices.set(face.face_id, { personId: face.suggestions[0].person_id, name: face.suggestions[0].name });
      }
      this.choices.set(choices);
    } catch (failure) {
      if (!guard.current()) return;
      // 412: too many reference faces to rank suggestions. Browsing without them still works.
      if ((failure as { status?: number }).status === 412 && this.wantsSuggestions()) retryWithoutSuggestions = true;
      else { this.error.set(true); this.retryAfter = after; }
    }
    finally { if (this.generation === generation) { this.loading.set(false); if (!guard.current()) this.error.set(true); } guard.dispose(); }
    if (!retryWithoutSuggestions) return;
    this.refusedSuggestions.set(true);
    await this.load(after, true);
    if (!this.error()) this.suggestionsSkipped.set(true);
  }
  protected toggle(id: number): void {
    if (!this.allowed() || this.busy() || this.pending() || this.uncertain() || this.changed() || !this.choices().has(id)) return;
    this.selected.update(value => { const next = new Set(value); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  protected toggleGroup(group: ReviewGroup, event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!this.allowed() || this.interactionLocked()) {
      // [checked] does not rewrite the DOM when its bound value is unchanged, so undo the click here.
      input.checked = group.selectedCount === group.ids.length;
      input.indeterminate = group.selectedCount > 0 && group.selectedCount < group.ids.length;
      return;
    }
    this.selected.update(value => {
      const next = new Set(value);
      for (const id of group.ids) { if (input.checked) next.add(id); else next.delete(id); }
      return next;
    });
  }
  protected clearSelection(): void {
    if (this.interactionLocked()) return;
    this.selected.set(new Set());
  }
  /** A tile with a person toggles its selection; a tile without one asks who it is. */
  protected activate(face: Face, tile: HTMLElement): void {
    if (this.interactionLocked()) return;
    if (this.choices().has(face.face_id)) this.toggle(face.face_id);
    else void this.chooseOther(face, tile);
  }
  protected choose(id: number, personId: number, name: string): void {
    if (!this.allowed() || this.busy() || this.pending() || this.uncertain() || this.changed() || !this.faces().some(face => face.face_id === id)) return;
    this.choices.update(value => new Map(value).set(id, { personId, name }));
  }
  protected chooseSuggestion(face: Face, personId: number, name: string): void {
    const before = this.choices().get(face.face_id)?.personId;
    this.choose(face.face_id, personId, name);
    // The face moves to another group, so its tile is re-created there: follow it.
    if (before !== personId && this.choices().get(face.face_id)?.personId === personId) this.focusAfterRender(() => this.tile(face.face_id));
  }
  protected async chooseOther(face: Face, focusTarget: FocusTarget): Promise<void> {
    if (!this.allowed() || this.interactionLocked() || this.chooser) return;
    this.choosing.set(true);
    const generation = this.generation;
    const guard = this.capture();
    const before = this.choices().get(face.face_id)?.personId;
    let moved = false;
    try {
      const { PersonSelectorDialogComponent } = await import('../gallery/person-selector-dialog.component');
      if (!guard.current()) return;
      const ref = this.dialog.open(PersonSelectorDialogComponent, { width: 'min(95vw, 28rem)', data: { allowCreate: false } });
      this.chooser = ref;
      const result = await firstValueFrom(ref.afterClosed());
      if (guard.current() && result?.kind === 'select' && typeof result.person.name === 'string') {
        this.choose(face.face_id, result.person.id, result.person.name);
        // Picking a person by hand is an explicit decision: tick the face so it is in the next preview.
        if (this.choices().get(face.face_id)?.personId === result.person.id) {
          this.selected.update(value => new Set(value).add(face.face_id));
          moved = result.person.id !== before;
        }
      }
      if (this.chooser === ref) this.chooser = null;
    } catch { if (guard.current()) this.error.set(true); }
    finally {
      if (generation === this.generation) this.choosing.set(false);
      if (guard.current()) { if (moved) this.focusAfterRender(() => this.tile(face.face_id)); else focusTarget.focus(); }
      guard.dispose();
    }
  }
  protected skip(id: number): void {
    if (!this.allowed() || this.busy() || this.pending()) return;
    const order = this.groups().flatMap(group => group.ids);
    const index = order.indexOf(id);
    const neighbour = index < 0 ? undefined : order[index + 1] ?? order[index - 1];
    this.faces.update(value => value.filter(face => face.face_id !== id));
    this.selected.update(value => { const next = new Set(value); next.delete(id); return next; });
    if (index >= 0) this.focusAfterRender(() => neighbour === undefined ? null : this.tile(neighbour));
  }
  private tile(faceId: number): HTMLElement | null {
    return this.host.nativeElement.querySelector<HTMLElement>(`[data-review-face="${faceId}"] [data-review-tile]`);
  }
  /** Focus what `pick` finds once the queue has re-rendered, or the queue itself when it finds nothing. */
  private focusAfterRender(pick: () => HTMLElement | null | undefined): void {
    const generation = this.generation;
    afterNextRender(() => { if (this.generation === generation && this.allowed()) (pick() ?? this.host.nativeElement).focus(); }, { injector: this.injector });
  }
  protected async rejectSuggestion(face: Face): Promise<void> {
    const choice = this.choices().get(face.face_id);
    if (!choice || !this.allowed() || this.interactionLocked()) return;
    if (!this.faces().some(value => value === face)) return;
    this.feedbackGuard?.dispose();
    const guard = this.capture(); this.feedbackGuard = guard;
    this.feedbackReceipt.set(null);
    await this.writeFeedback({ face, choice, receiptId: '' }, false, guard);
  }
  protected async undoFeedback(): Promise<void> {
    const receipt = this.feedbackReceipt(), guard = this.feedbackGuard;
    if (!receipt || !guard || !this.allowed() || this.interactionLocked()) return;
    if (!guard.current()) { this.reset(); this.error.set(true); return; }
    await this.writeFeedback(receipt, true, guard);
  }
  private async writeFeedback(captured: FeedbackReceipt, undo: boolean, guard: StalenessGuard): Promise<void> {
    const generation = this.generation;
    this.busy.set(true); this.error.set(false);
    let accepted = false;
    try {
      const body = { face_id: captured.face.face_id, person_id: captured.choice.personId,
        identity_token: captured.face.identity_token, expected_person_name: captured.choice.name };
      const result = await firstValueFrom(this.api.post<components['schemas']['FaceReviewFeedbackResponse']>(
        `/faces/review/feedback${undo ? '/undo' : ''}`, undo ? { ...body, receipt_id: captured.receiptId } : body));
      if (!guard.current()) return;
      accepted = true;
      this.feedbackReceipt.set(undo ? null : { ...captured, receiptId: result.receipt_id });
      const response = await firstValueFrom(this.api.get<Response>('/faces/review', {
        face_id: captured.face.face_id, limit: 1, suggest: this.wantsSuggestions(),
      }));
      if (!guard.current()) return;
      const refreshed = response.faces.find(face => face.face_id === captured.face.face_id);
      this.faces.update(value => value.flatMap(face => face.face_id === captured.face.face_id ? refreshed ? [refreshed] : [] : [face]));
      this.total.set(response.total_unassigned);
      this.choices.update(value => {
        const next = new Map(value); next.delete(captured.face.face_id);
        const choice = refreshed?.suggestions[0];
        if (choice) next.set(captured.face.face_id, { personId: choice.person_id, name: choice.name });
        return next;
      });
      // A different suggestion needs a fresh explicit selection. Other faces stay selected.
      this.selected.update(value => { const next = new Set(value); next.delete(captured.face.face_id); return next; });
    } catch {
      if (guard.current()) { this.error.set(true); this.changed.set(accepted); this.uncertain.set(!accepted); }
    } finally {
      if (this.generation === generation) {
        this.busy.set(false);
        if (!guard.current()) { this.reset(); this.error.set(true); }
        else afterNextRender(() => { if (guard.current()) this.host.nativeElement.focus(); }, { injector: this.injector });
      }
    }
  }
  protected preview(event: Event): void {
    if (!this.allowed() || this.interactionLocked()) return;
    const captured = this.faces().flatMap(face => {
      const choice = this.choices().get(face.face_id);
      return choice && this.selected().has(face.face_id) ? [{ ...choice, faceId: face.face_id, token: face.identity_token }] : [];
    });
    if (!captured.length) return;
    this.returnFocus = event.currentTarget as HTMLElement;
    const guard = this.capture(); this.planGuard = guard; this.pending.set(captured);
    afterNextRender(() => { if (this.planGuard === guard && guard.current()) this.previewPanel()?.nativeElement.focus(); }, { injector: this.injector });
  }
  protected cancel(event: Event): void {
    event.preventDefault(); event.stopPropagation();
    if (this.busy()) return;
    this.pending.set(null); this.planGuard?.dispose(); this.planGuard = null;
    if (this.returnFocus?.isConnected && this.allowed()) this.returnFocus.focus();
  }
  protected async apply(): Promise<void> {
    const plan = this.pending(), guard = this.planGuard;
    if (!plan || !guard?.current() || this.busy()) return;
    this.busy.set(true); this.error.set(false); this.receipt.set({ assigned: 0, skipped: 0, reasons: [] });
    try {
      for (const group of this.planGroups()) {
        if (!guard.current()) return;
        const groupFaces = plan.filter(face => face.personId === group.personId);
        for (let start = 0; start < groupFaces.length; start += ASSIGN_FACES_MAX) {
          const faces = groupFaces.slice(start, start + ASSIGN_FACES_MAX);
          const report = await firstValueFrom(this.api.post<AssignmentReport>(`/persons/${group.personId}/assign_faces`, {
            face_ids: faces.map(face => face.faceId), only_unassigned: true, tolerant: true,
            expected_face_tokens: Object.fromEntries(faces.map(face => [face.faceId, face.token])), expected_person_name: group.name,
          }));
          if (!guard.current()) return;
          const reasons = [
            [report.already, I18N.persons.review_queue.already], [report.missing, I18N.persons.review_queue.missing],
            [report.skipped_model, I18N.persons.review_queue.model_mismatch], [report.skipped_hidden, I18N.persons.review_queue.already_assigned],
            [report.skipped_assigned, I18N.persons.review_queue.already_assigned], [report.skipped_changed, I18N.persons.review_queue.face_changed],
          ] as const;
          this.receipt.update(value => ({ assigned: (value?.assigned ?? 0) + report.assigned_count, skipped: (value?.skipped ?? 0) + faces.length - report.assigned_count,
            reasons: [...(value?.reasons ?? []), ...reasons.filter(([ids]) => ids.length).map(([ids, label]) => ({ name: group.name, label, count: ids.length }))] }));
          this.boxes.clear();
          const settled = new Set(faces.map(face => face.faceId));
          this.faces.update(value => value.filter(face => !settled.has(face.face_id)));
        }
      }
      if (guard.current()) { this.pending.set(null); this.selected.set(new Set()); if ((this.receipt()?.skipped ?? 0) > 0) { this.changed.set(true); this.error.set(true); } }
    } catch {
      if (guard.current()) { this.error.set(true); this.uncertain.set(true); this.pending.set(null); }
    } finally {
      if (this.planGuard === guard) {
        this.busy.set(false);
        if (!guard.current()) { this.pending.set(null); this.faces.set([]); this.selected.set(new Set()); this.total.set(0); this.error.set(true); this.uncertain.set(true); }
        // Move to the outcome, so it scrolls into view and is announced: the alert after a failure, else the receipt.
        else afterNextRender(() => { if (guard.current() && !this.pending()) ((this.uncertain() ? this.queueAlert() : this.receiptStatus())?.nativeElement ?? this.host.nativeElement).focus(); }, { injector: this.injector });
        this.planGuard = null;
      }
      guard.dispose();
    }
  }
}
