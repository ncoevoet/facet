import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, Injector, input, signal, untracked, viewChild } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18N } from '../../core/i18n/keys';
import { StalenessGuard, StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';

type Face = components['schemas']['FaceReviewItem'];
type Response = components['schemas']['FaceReviewResponse'];
interface Choice { personId: number; name: string }
interface CapturedFace extends Choice { faceId: number; token: string }
interface FeedbackReceipt { face: Face; choice: Choice; receiptId: string }
interface ReceiptReason { name: string; label: string; count: number }
interface AssignmentReport { assigned_count: number; already: number[]; missing: number[]; skipped_model: number[]; skipped_hidden: number[]; skipped_assigned: number[]; skipped_changed: number[] }

@Component({
  selector: 'app-face-review-queue',
  imports: [MatButtonModule, MatIconModule, RouterLink, TranslatePipe, FixedPipe, FaceThumbnailUrlPipe, ContextHelpComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0', tabindex: '-1' },
  template: `
    <div class="flex flex-wrap items-center gap-2 py-3">
      <div class="min-w-0 flex-1">
        @if (!error()) { <p role="status" class="m-0 text-sm">{{ I18N.persons.review_queue.total | translate:{ count: total() } }}</p> }
      </div>
      <button mat-stroked-button data-queue-reload [disabled]="loading() || busy()" (click)="load(0)"><mat-icon>refresh</mat-icon>{{ I18N.persons.review_queue.reload | translate }}</button>
      <button mat-flat-button data-review-selected [disabled]="!selected().size || loading() || busy() || uncertain() || changed() || choosing()" (click)="preview($event)"><mat-icon>fact_check</mat-icon>{{ I18N.persons.review_queue.preview | translate:{ count: selected().size } }}</button>
    </div>
    @if (pending()) {
      <section #previewPanel tabindex="-1" data-assignment-preview class="mb-4 flex flex-col gap-2 rounded-xl border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface-container)] p-4" (keydown.escape)="cancel($event)">
        <h3 class="m-0 text-sm font-medium">{{ I18N.persons.review_queue.confirm_title | translate }}</h3>
        <ul class="my-2 max-h-48 overflow-y-auto pl-5 text-sm">
          @for (group of planGroups(); track group.personId) { <li>{{ group.name }} · {{ group.count }}</li> }
        </ul>
        <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.confirm_help | translate }}</p>
        <div class="flex justify-end gap-2"><button mat-button [disabled]="busy()" (click)="cancel($event)">{{ I18N.dialog.cancel | translate }}</button><button mat-flat-button data-confirm-assignment [disabled]="busy()" (click)="apply()"><mat-icon>check</mat-icon>{{ I18N.persons.review_queue.confirm | translate }}</button></div>
      </section>
    }
    @if (receipt(); as result) {
      <p role="status" data-assignment-receipt class="text-sm">{{ I18N.persons.review_queue.receipt | translate:{ assigned: result.assigned, skipped: result.skipped } }}</p>
      @if (result.reasons.length) { <details data-receipt-reasons class="mb-3 text-xs"><summary class="min-h-11 cursor-pointer">{{ I18N.persons.review_queue.receipt_details | translate }}</summary><ul class="pl-5">@for (reason of result.reasons; track $index) { <li>{{ reason.name }} · {{ reason.label | translate }}: {{ reason.count }}</li> }</ul></details> }
    }
    @if (feedbackReceipt(); as result) {
      <div role="status" data-feedback-receipt class="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span>{{ I18N.persons.review_queue.feedback_saved | translate:{name: result.choice.name} }}</span>
        <button mat-stroked-button data-feedback-undo [disabled]="interactionLocked()" (click)="undoFeedback()"><mat-icon>undo</mat-icon>{{ I18N.persons.review_queue.feedback_undo | translate }}</button>
      </div>
    }
    @if (error()) {
      <div role="alert" class="mb-3 rounded border border-[var(--mat-sys-outline)] p-3 text-sm">
        {{ (uncertain() ? I18N.persons.review_queue.uncertain : changed() ? I18N.persons.review_queue.changed : I18N.persons.review_queue.read_error) | translate }}
        @if (!busy()) { <button mat-stroked-button (click)="load(0)"><mat-icon>refresh</mat-icon>{{ I18N.gallery.load_error.retry | translate }}</button> }
        @if (mode() === 'matches') { <button mat-stroked-button data-browse-without-matches (click)="withoutSuggestions.set(true); load(0)">{{ I18N.persons.review_queue.without_matches | translate }}</button> }
      </div>
    }
    @if (suggestionsSkipped() && !error()) { <p role="status" data-suggestions-skipped class="mb-3 text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.suggestions_skipped | translate }}</p> }
    @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
    @for (group of groups(); track group.id) {
      <section class="mb-4">
        <h3 class="m-0 mb-2 break-words text-sm font-medium">{{ group.name ? (I18N.persons.review_queue.group | translate:{ name: group.name }) : (I18N.persons.review_queue.no_suggestion | translate) }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[repeat(auto-fill,minmax(25rem,1fr))]">
          @for (face of group.faces; track face.face_id) {
            <article class="min-w-0 rounded-lg border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-low)] p-3" [attr.data-review-face]="face.face_id" [attr.aria-label]="I18N.persons.review_queue.face_label | translate:{id: face.face_id}">
              <div class="flex items-start gap-3">
                <div class="relative shrink-0">
                  <img [src]="face.face_id | faceThumbnailUrl" alt="" class="h-24 w-24 rounded object-cover" />
                  <a routerLink="/photo" [queryParams]="{path:face.photo_path}" target="_blank" rel="noopener" [attr.aria-label]="I18N.persons.review_queue.open_photo | translate" [attr.title]="I18N.persons.review_queue.open_photo | translate"
                     class="absolute bottom-1 right-1 inline-flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80 pointer-coarse:h-11 pointer-coarse:w-11"><mat-icon class="!text-base !h-4 !w-4 !leading-4" aria-hidden="true">open_in_new</mat-icon></a>
                </div>
                <div class="min-w-0 flex-1">
                  @if (choices().get(face.face_id); as choice) {
                    <label class="flex min-h-11 cursor-pointer items-center gap-2 text-sm"><input type="checkbox" [checked]="selected().has(face.face_id)" [disabled]="interactionLocked()" [attr.aria-label]="I18N.persons.review_queue.assign_label | translate:{id: face.face_id, name: choice.name}" (change)="toggle(face.face_id)" /><span class="min-w-0 break-words">{{ choice.name }}</span></label>
                  }
                  <div class="flex flex-wrap items-center gap-1">
                    @for (suggestion of face.suggestions; track suggestion.person_id) {
                      <button mat-stroked-button class="!min-h-11 !px-3" [class.!bg-[var(--mat-sys-secondary-container)]]="choices().get(face.face_id)?.personId === suggestion.person_id" [disabled]="interactionLocked()" [attr.aria-pressed]="choices().get(face.face_id)?.personId === suggestion.person_id" [attr.aria-label]="I18N.persons.review_queue.similarity_label | translate:{ name: suggestion.name, value: suggestion.similarity * 100 }" (click)="choose(face.face_id, suggestion.person_id, suggestion.name)">@if (choices().get(face.face_id)?.personId === suggestion.person_id) { <mat-icon>check</mat-icon> }<span class="max-w-40 truncate">{{ suggestion.name }}</span> · {{ suggestion.similarity * 100 | fixed:0 }}</button>
                    }
                    <button mat-stroked-button [disabled]="interactionLocked()" (click)="chooseOther(face, $event)"><mat-icon>person_search</mat-icon>{{ I18N.persons.review_queue.choose_person | translate }}</button>
                    @if (choices().get(face.face_id); as choice) {
                      <button mat-button data-not-person [disabled]="interactionLocked()" (click)="rejectSuggestion(face)"><mat-icon>block</mat-icon>{{ I18N.persons.review_queue.not_person | translate:{name: choice.name} }}</button>
                    }
                    <button mat-button class="!text-[var(--mat-sys-on-surface-variant)]" [disabled]="busy() || !!pending() || choosing()" (click)="skip(face.face_id)"><mat-icon>skip_next</mat-icon>{{ I18N.persons.review_queue.skip | translate }}</button>
                  </div>
                </div>
              </div>
              @if (face.embedding_state !== 'ready') { <p class="my-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ (face.embedding_state === 'incompatible' ? I18N.persons.review_queue.model_mismatch : I18N.persons.review_queue.matching_unavailable) | translate }}</p> }
            </article>
          }
        </div>
      </section>
    }
    @if (!loading() && !error() && !groups().length) { <p class="py-6 text-center text-sm text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.review_queue.empty | translate }}</p> }
    @if (nextAfter() !== null) { <button mat-stroked-button data-queue-next [disabled]="loading() || busy() || !!pending()" (click)="load(nextAfter()!)">{{ I18N.ui.buttons.load_more | translate }}</button> }
    <app-context-help [label]="I18N.persons.review_queue.about" [keys]="[I18N.persons.review_queue.help]" />
  `,
})
export class FaceReviewQueueComponent {
  focus(): void { this.host.nativeElement.focus(); }
  protected readonly I18N = I18N;
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
  protected readonly withoutSuggestions = signal(false);
  protected readonly suggestionsSkipped = signal(false);
  protected readonly pending = signal<readonly CapturedFace[] | null>(null);
  protected readonly interactionLocked = computed(() => this.busy() || !!this.pending() || this.uncertain() || this.changed() || this.choosing());
  protected readonly receipt = signal<{ assigned: number; skipped: number; reasons: ReceiptReason[] } | null>(null);
  protected readonly feedbackReceipt = signal<FeedbackReceipt | null>(null);
  protected readonly groups = computed(() => {
    const groups = new Map<number, { id: number; name: string; faces: Face[] }>();
    for (const face of this.faces()) {
      const choice = this.choices().get(face.face_id);
      const id = choice?.personId ?? 0;
      const group = groups.get(id) ?? { id, name: choice?.name ?? '', faces: [] };
      group.faces.push(face); groups.set(id, group);
    }
    return [...groups.values()];
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
  protected async load(after: number): Promise<void> {
    if (!this.allowed() || this.busy() || (after > 0 && (this.loading() || this.pending() || this.uncertain() || this.changed() || this.choosing()))) return;
    if (after === 0) this.reset();
    this.loading.set(true); this.error.set(false);
    const guard = this.capture(), generation = this.generation;
    let retryWithoutSuggestions = false;
    try {
      const response = await firstValueFrom(this.api.get<Response>('/faces/review', { after_id: after, limit: 48, suggest: this.mode() === 'matches' && !this.withoutSuggestions() }));
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
      if ((failure as { status?: number }).status === 412 && this.mode() === 'matches' && !this.withoutSuggestions()) retryWithoutSuggestions = true;
      else this.error.set(true);
    }
    finally { if (this.generation === generation) { this.loading.set(false); if (!guard.current()) this.error.set(true); } guard.dispose(); }
    if (!retryWithoutSuggestions) return;
    this.withoutSuggestions.set(true);
    await this.load(after);
    if (!this.error()) this.suggestionsSkipped.set(true);
  }
  protected toggle(id: number): void {
    if (!this.allowed() || this.busy() || this.pending() || this.uncertain() || this.changed() || !this.choices().has(id)) return;
    this.selected.update(value => { const next = new Set(value); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  protected choose(id: number, personId: number, name: string): void {
    if (!this.allowed() || this.busy() || this.pending() || this.uncertain() || this.changed() || !this.faces().some(face => face.face_id === id)) return;
    this.choices.update(value => new Map(value).set(id, { personId, name }));
  }
  protected async chooseOther(face: Face, event: Event): Promise<void> {
    if (!this.allowed() || this.interactionLocked() || this.chooser) return;
    this.choosing.set(true);
    const generation = this.generation;
    const guard = this.capture();
    const trigger = event.currentTarget as HTMLElement | null;
    try {
      const { PersonSelectorDialogComponent } = await import('../gallery/person-selector-dialog.component');
      if (!guard.current()) return;
      const ref = this.dialog.open(PersonSelectorDialogComponent, { width: 'min(95vw, 28rem)', data: { allowCreate: false } });
      this.chooser = ref;
      const result = await firstValueFrom(ref.afterClosed());
      if (guard.current() && result?.kind === 'select' && typeof result.person.name === 'string') {
        this.choose(face.face_id, result.person.id, result.person.name);
        // Picking a person by hand is an explicit decision: tick the face so it is in the next preview.
        if (this.choices().get(face.face_id)?.personId === result.person.id) this.selected.update(value => new Set(value).add(face.face_id));
      }
      if (this.chooser === ref) this.chooser = null;
    } catch { if (guard.current()) this.error.set(true); }
    finally {
      if (generation === this.generation) this.choosing.set(false);
      if (guard.current() && trigger?.isConnected) trigger.focus();
      guard.dispose();
    }
  }
  protected skip(id: number): void {
    if (!this.allowed() || this.busy() || this.pending()) return;
    this.faces.update(value => value.filter(face => face.face_id !== id));
    this.selected.update(value => { const next = new Set(value); next.delete(id); return next; });
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
        face_id: captured.face.face_id, limit: 1, suggest: this.mode() === 'matches' && !this.withoutSuggestions(),
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
        const faces = plan.filter(face => face.personId === group.personId);
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
      if (guard.current()) { this.pending.set(null); this.selected.set(new Set()); if ((this.receipt()?.skipped ?? 0) > 0) { this.changed.set(true); this.error.set(true); } }
    } catch {
      if (guard.current()) { this.error.set(true); this.uncertain.set(true); this.pending.set(null); }
    } finally {
      if (this.planGuard === guard) {
        this.busy.set(false);
        if (!guard.current()) { this.pending.set(null); this.faces.set([]); this.selected.set(new Set()); this.total.set(0); this.error.set(true); this.uncertain.set(true); }
        else afterNextRender(() => { if (guard.current() && !this.pending()) this.host.nativeElement.focus(); }, { injector: this.injector });
        this.planGuard = null;
      }
      guard.dispose();
    }
  }
}
