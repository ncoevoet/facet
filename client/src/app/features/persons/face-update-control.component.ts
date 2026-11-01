import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, Injector, output, signal, untracked, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { SlicePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import type { components } from '../../core/api/schema';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ScanService } from '../../core/services/scan.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';

type Job = components['schemas']['FaceUpdateRecord'];
type Preview = components['schemas']['FaceUpdatePreview'];
type Problems = components['schemas']['FaceUpdateItemsResponse'];
interface StartRequest { job_id: string; expected_model: string; mode: 'missing' | 'redetect' | 'repair'; token: string | null; owner: string | null; status: unknown }

@Component({
  selector: 'app-face-update-control',
  imports: [MatButtonModule, MatIconModule, SlicePipe, TranslatePipe, ContextHelpComponent, RouterLink, FilenamePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    @if (scan.canLaunch()) {
      <div class="flex justify-end">
        <button #trigger mat-button data-update-faces [disabled]="blocked()" [attr.aria-expanded]="expanded()" aria-controls="face-update-panel" (click)="open()"><mat-icon>person_search</mat-icon>{{ I18N.persons.face_update.title | translate }}</button>
      </div>
      @if (expanded()) {
        <section #panel id="face-update-panel" tabindex="-1" aria-labelledby="face-update-heading" class="mb-3 rounded border border-[var(--mat-sys-outline-variant)] p-3" (keydown.escape)="close($event)">
          <div class="flex items-center gap-2">
            <h3 id="face-update-heading" class="m-0 flex-1 text-sm font-medium">{{ I18N.persons.face_update.title | translate }}</h3>
            <button mat-icon-button [attr.aria-label]="I18N.dialog.close | translate" (click)="close($event)"><mat-icon>close</mat-icon></button>
          </div>
          @if (error()) { <p role="alert" class="text-sm">{{ (request() ? I18N.persons.face_update.start_unknown : startRefused() ? I18N.persons.face_update.start_refused : stopUncertain() ? I18N.persons.face_update.stop_unknown : I18N.persons.face_update.read_error) | translate }}</p> }
          @if (preview(); as scope) {
            <p class="my-2 text-sm">{{ (scope.mode === 'redetect' ? I18N.persons.face_update.redetect_scope : I18N.persons.face_update.scope) | translate:{count: scope.eligible_photos} }}</p>
            @if (scope.mode === 'redetect') {
              <p class="my-2 text-xs">{{ I18N.persons.face_update.affected | translate:{automatic: scope.automatic_faces, assigned: scope.assigned_faces, manual: scope.manual_faces} }}</p>
              <p class="my-2 text-sm">{{ I18N.persons.face_update.redetect_warning | translate }}</p>
            }
            <p class="my-2 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.persons.face_update.model | translate:{model: scope.model} }}</p>
            @if (scope.pending_person_matches) { <p class="my-2 text-xs">{{ I18N.persons.face_update.pending_matches | translate:{count: scope.pending_person_matches} }}</p> }
            <button mat-flat-button data-start-faces [disabled]="!!busy() || !!request() || (scope.eligible_photos === 0 && !scope.pending_person_matches)" (click)="start()">{{ (scope.eligible_photos === 0 ? I18N.persons.face_update.repair_matches : scope.mode === 'redetect' ? I18N.persons.face_update.redetect_start : I18N.persons.face_update.start) | translate }}</button>
          }
          @if (job(); as result) {
            <div role="status" data-face-update-receipt class="my-3 text-sm">
              @if (result.mode === 'redetect') { <p class="my-1 font-medium">{{ I18N.persons.face_update.redetect_receipt | translate }}</p> }
              <p class="my-1">{{ stateKey() | translate }} · <code>{{ result.job_id | slice:0:8 }}</code></p>
              <p class="my-1">{{ I18N.persons.face_update.progress | translate:{processed: result.processed, total: result.total} }}</p>
              <p class="my-1 text-xs">{{ I18N.persons.face_update.counts | translate:{added: result.added_faces, empty: result.empty, skipped: result.skipped, failed: result.failed} }}</p>
              @if (result.mode === 'redetect') { <p class="my-1 text-xs">{{ I18N.persons.face_update.redetect_counts | translate:{refreshed: result.refreshed_faces, removed: result.removed_faces, refused: result.refused} }}</p> }
              @if (result.repaired_people) { <p class="my-1 text-xs">{{ I18N.persons.face_update.repaired_matches | translate:{count: result.repaired_people} }}</p> }
              @if (active() && (error() || !result.controlled_by_worker)) { <p class="my-1 text-xs">{{ I18N.persons.face_update.recorded_only | translate }}</p> }
              @if (result.stop_requested && active()) { <p class="my-1 text-xs">{{ I18N.persons.face_update.stop_requested | translate }}</p> }
              @if (result.error_code) { <p class="my-1 text-xs">{{ errorKey() | translate }}</p> }
            </div>
            @if (stopTarget()) {
              <div data-stop-faces-preview class="my-2 flex flex-wrap items-center gap-2 text-sm">
                <span>{{ I18N.persons.face_update.stop_confirm | translate }}</span>
                <button mat-button data-cancel-stop-faces [disabled]="!!busy()" (click)="cancelStop($event)">{{ I18N.dialog.cancel | translate }}</button>
                <button mat-stroked-button data-confirm-stop-faces [disabled]="!!busy()" (click)="stop()">{{ I18N.persons.face_update.stop | translate }}</button>
              </div>
            } @else if (active() && !result.stop_requested) {
              <button #stopTrigger mat-button data-stop-faces [disabled]="!!busy() || stopUncertain()" (click)="stopTarget.set(result.job_id)">{{ I18N.persons.face_update.stop | translate }}</button>
            }
            @if (!active()) {
              <button mat-button data-review-updated-faces [disabled]="!!busy()" (click)="review()">{{ I18N.persons.review_queue.matches | translate }}</button>
            }
            @if (result.refused || result.failed) {
              <button mat-button data-read-face-problems [disabled]="!!busy()" (click)="readProblems()">{{ I18N.persons.face_update.review_problems | translate }}</button>
            }
            @if (problems(); as page) {
              <section #problemsPanel tabindex="-1" class="my-2 rounded border border-[var(--mat-sys-outline-variant)] p-2" [attr.aria-label]="I18N.persons.face_update.review_problems | translate">
                <p class="my-1 text-xs">{{ I18N.persons.face_update.problems_count | translate:{shown: page.items.length, total: page.total} }}</p>
                <ul class="m-0 max-h-64 list-none overflow-auto p-0">
                  @for (item of problemRows(); track item.path) {
                    <li class="border-b border-[var(--mat-sys-outline-variant)] py-2 text-xs last:border-b-0">
                      <a mat-button class="!min-h-11 max-w-full !justify-start" routerLink="/photo" [queryParams]="{path:item.path}" target="_blank" rel="noopener"><span class="min-w-0 truncate">{{ item.path | filename }}</span><mat-icon>open_in_new</mat-icon></a>
                      <p class="m-0">{{ item.label | translate }}</p>
                    </li>
                  }
                </ul>
                @if (page.next_after) { <button mat-button data-more-face-problems [disabled]="!!busy()" (click)="readProblems(page.next_after)">{{ I18N.ui.buttons.load_more | translate }}</button> }
              </section>
            }
            @if (problemsError()) { <p role="alert" class="text-xs">{{ I18N.persons.face_update.problems_error | translate }}</p> }
          }
          <div class="mt-2 flex flex-wrap items-center gap-2">
            @if (request()) {
              <button mat-button data-recover-face-start [disabled]="!!busy()" (click)="readJob(request()!.job_id)">{{ I18N.persons.face_update.read_status | translate }}</button>
              <button mat-button data-retry-face-start [disabled]="!!busy()" (click)="retryStart()">{{ I18N.persons.face_update.retry_request | translate }}</button>
            } @else if (job()) {
              <button mat-button data-read-face-status [disabled]="!!busy()" (click)="readJob(job()!.job_id)">{{ I18N.persons.face_update.read_status | translate }}</button>
            }
            <button mat-button data-face-update-overview [disabled]="!!busy() || !!request() || active()" (click)="readOverview()">{{ I18N.persons.face_update.refresh | translate }}</button>
            @if (busy()) { <span role="status" class="text-xs">{{ I18N.ui.labels.loading | translate }}</span> }
          </div>
          @if (historyRows().length) {
            <details class="mt-2 text-xs"><summary class="min-h-11 cursor-pointer">{{ I18N.persons.face_update.recent | translate }}</summary>
              <ul class="m-0 max-h-48 list-none overflow-auto p-0">
                @for (entry of historyRows(); track entry.record.job_id) {
                  <li><button mat-button class="!min-h-11" [disabled]="!!busy() || !!request()" (click)="chooseJob(entry.record)">{{ entry.label | translate }} · {{ entry.record.job_id | slice:0:8 }} · {{ entry.record.processed }}/{{ entry.record.total }}</button></li>
                }
              </ul>
            </details>
          }
          <details class="mt-2 text-xs"><summary class="min-h-11 cursor-pointer">{{ I18N.persons.face_update.more_tools | translate }}</summary>
            <div class="flex flex-wrap gap-2">
              <button mat-button data-redetect-faces [disabled]="!!busy() || !!request() || active()" (click)="readOverview('redetect')">{{ I18N.persons.face_update.redetect_start | translate }}</button>
              <button mat-button data-missing-faces [disabled]="!!busy() || !!request() || active()" (click)="readOverview('missing')">{{ I18N.persons.face_update.missing_mode | translate }}</button>
            </div>
          </details>
          <app-context-help [label]="I18N.persons.face_update.about" [keys]="[I18N.persons.face_update.help]" />
        </section>
      }
    }
  `,
})
export class FaceUpdateControlComponent {
  protected readonly I18N = I18N;
  protected readonly scan = inject(ScanService);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');
  private readonly trigger = viewChild<unknown, ElementRef<HTMLElement>>('trigger', { read: ElementRef });
  private readonly stopTrigger = viewChild<unknown, ElementRef<HTMLElement>>('stopTrigger', { read: ElementRef });
  private readonly problemsPanel = viewChild<ElementRef<HTMLElement>>('problemsPanel');
  readonly reviewRequested = output<void>();
  protected readonly blocked = signal(false);
  protected readonly expanded = signal(false);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly job = signal<Job | null>(null);
  protected readonly request = signal<StartRequest | null>(null);
  protected readonly stopTarget = signal<string | null>(null);
  protected readonly busy = signal<'read' | 'start' | 'stop' | null>(null);
  protected readonly error = signal(false);
  protected readonly stopUncertain = signal(false);
  protected readonly startRefused = signal(false);
  protected readonly problems = signal<Problems | null>(null);
  protected readonly problemsError = signal(false);
  private overviewMode: 'missing' | 'redetect' = 'missing';
  private readonly history = signal<Job[]>([]);
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private previewContext: StartRequest | null = null;
  private panelContext: StartRequest | null = null;
  private readonly states = {
    queued: I18N.persons.face_update.queued, running: I18N.persons.face_update.running,
    completed: I18N.persons.face_update.completed, partial: I18N.persons.face_update.partial,
    cancelled: I18N.persons.face_update.cancelled, failed: I18N.persons.face_update.failed,
  };
  protected readonly stateKey = computed(() => this.states[this.job()?.state ?? 'queued']);
  protected readonly errorKey = computed(() => this.job()?.error_code === 'model_unavailable' ? I18N.persons.face_update.model_unavailable
    : this.job()?.error_code === 'model_changed' ? I18N.persons.face_update.model_changed : I18N.persons.face_update.job_error);
  protected readonly active = computed(() => this.job()?.state === 'queued' || this.job()?.state === 'running');
  protected readonly historyRows = computed(() => this.history().map(record => ({ record, label: this.states[record.state] })));
  private readonly problemLabels: Readonly<Record<string, string>> = {
    faces_changed: I18N.persons.face_update.problem_changed,
    confirmed_face_not_matched: I18N.persons.face_update.problem_unmatched,
    identity_not_consistent: I18N.persons.face_update.problem_identity,
    complexity_limit: I18N.persons.face_update.problem_complex,
    invalid_detection_geometry: I18N.persons.face_update.problem_geometry,
    source_changed: I18N.persons.face_update.problem_source,
  };
  protected readonly problemRows = computed(() => (this.problems()?.items ?? []).map(item => ({ ...item, label: this.problemLabels[item.error_code ?? ''] ?? I18N.persons.face_update.problem_failed })));

  constructor() {
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) { this.blocked.set(true); this.reset(true); }
      else if (event instanceof NavigationEnd || event instanceof NavigationSkipped || event instanceof NavigationError || (event instanceof NavigationCancel && event.code !== NavigationCancellationCode.Redirect)) this.blocked.set(!this.ownsRoute());
    });
    effect(() => {
      if (!this.scan.canLaunch()) { untracked(() => this.reset(true)); return; }
      this.auth.identity(); this.auth.status();
      untracked(() => { this.blocked.set(!!this.router.currentNavigation() || !this.ownsRoute()); this.reset(true); });
    });
    this.destroyRef.onDestroy(() => this.reset(true));
  }
  private ownsRoute(): boolean { return this.router.parseUrl(this.router.url).root.children['primary']?.segments.map(value => value.path).join('/') === 'persons'; }
  private allowed(): boolean { return !this.destroyRef.destroyed && !this.blocked() && this.scan.canLaunch(); }
  private current(context: StartRequest): boolean { return this.allowed() && context.owner === this.auth.identity() && context.status === this.auth.status() && context.token === this.auth.token; }
  private canAct(): boolean { return this.allowed() && this.expanded() && !!this.panelContext && this.current(this.panelContext); }
  private context(model: string): StartRequest {
    const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
    return { job_id: id, expected_model: model, mode: 'missing', owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
  }
  private capture() {
    const generation = this.generation, token = this.auth.token;
    return this.guards.create(this.destroyRef, { track: 'status', valid: () => this.canAct() && this.generation === generation && this.auth.token === token });
  }
  private clearTimer(): void { if (this.timer) clearTimeout(this.timer); this.timer = null; }
  private reset(privateState: boolean): void {
    this.generation++; this.clearTimer(); this.expanded.set(false); this.busy.set(null); this.error.set(false); this.stopUncertain.set(false); this.startRefused.set(false); this.preview.set(null); this.previewContext = null; this.stopTarget.set(null);
    this.panelContext = null; this.job.set(null); this.history.set([]);
    this.problems.set(null); this.problemsError.set(false); this.overviewMode = 'missing';
    if (privateState) this.request.set(null);
  }
  protected async open(): Promise<void> {
    if (!this.allowed()) return;
    if (this.expanded()) { this.close(); return; }
    if (this.request() && !this.current(this.request()!)) { this.reset(true); return; }
    this.panelContext = this.context('');
    this.expanded.set(true);
    const generation = this.generation;
    afterNextRender(() => { if (generation === this.generation && this.allowed() && this.expanded()) this.panel()?.nativeElement.focus(); }, { injector: this.injector });
    if (this.request()) await this.readJob(this.request()!.job_id);
    else await this.readOverview();
  }
  protected close(event?: Event): void {
    if (this.stopTarget() && !this.busy()) { this.cancelStop(event); return; }
    event?.preventDefault(); event?.stopPropagation(); this.reset(false);
    if (this.allowed()) this.trigger()?.nativeElement.focus();
  }
  protected cancelStop(event?: Event): void {
    event?.preventDefault(); event?.stopPropagation(); this.stopTarget.set(null);
    const generation = this.generation;
    afterNextRender(() => { if (generation === this.generation && this.canAct()) this.stopTrigger()?.nativeElement.focus(); }, { injector: this.injector });
  }
  private focusPanel(generation: number): void {
    afterNextRender(() => { if (generation === this.generation && this.canAct()) this.panel()?.nativeElement.focus(); }, { injector: this.injector });
  }
  protected async readOverview(mode: 'missing' | 'redetect' = this.overviewMode): Promise<void> {
    if (!this.canAct() || this.busy() || this.request() || this.active()) return;
    this.overviewMode = mode;
    this.clearTimer(); this.busy.set('read'); this.error.set(false);
    this.startRefused.set(false);
    this.preview.set(null); this.previewContext = null;
    this.problems.set(null); this.problemsError.set(false);
    const generation = this.generation, guard = this.capture();
    try {
      const [preview, jobs] = await Promise.all([
        firstValueFrom(mode === 'missing' ? this.api.get<Preview>('/scan/faces/preview') : this.api.get<Preview>('/scan/faces/preview', { mode })),
        firstValueFrom(this.api.get<Job[]>('/scan/faces/jobs')),
      ]);
      if (!guard.current()) return;
      if (preview.mode !== mode) throw new Error('Mismatched face update scope');
      this.preview.set(preview); this.previewContext = { ...this.context(preview.model), mode: preview.eligible_photos === 0 && preview.pending_person_matches ? 'repair' : mode }; this.history.set(jobs); this.job.set(null); this.stopTarget.set(null);
    } catch { if (guard.current()) this.error.set(true); }
    finally { if (generation === this.generation) this.busy.set(null); guard.dispose(); }
  }
  protected async start(): Promise<void> {
    const context = this.previewContext;
    if (!context || !this.current(context) || !this.canAct() || this.busy() || this.request() || (!this.preview()?.eligible_photos && !this.preview()?.pending_person_matches)) return;
    this.request.set(context); this.preview.set(null); this.previewContext = null; this.job.set(null); this.problems.set(null); this.problemsError.set(false);
    await this.writeStart(context, false);
  }
  protected async retryStart(): Promise<void> {
    const context = this.request();
    if (!context || !this.current(context) || !this.canAct() || this.busy()) return;
    await this.writeStart(context, true);
  }
  private async writeStart(context: StartRequest, retry: boolean): Promise<void> {
    this.clearTimer(); this.busy.set('start'); this.error.set(false);
    const generation = this.generation, guard = this.capture();
    try {
      const result = await firstValueFrom(this.api.post<Job>('/scan/faces/start', { job_id: context.job_id, expected_model: context.expected_model, mode: context.mode, confirm: true }));
      if (!guard.current()) return;
      if (result.job_id !== context.job_id) throw new Error('Mismatched face update receipt');
      this.request.set(null); this.job.set(result); this.updateHistory(result); this.armPoll();
    } catch (error) {
      if (guard.current()) {
        if (!retry && error instanceof HttpErrorResponse && [400, 403, 409, 422].includes(error.status)) {
          this.request.set(null); this.startRefused.set(true);
        }
        this.error.set(true);
      }
    }
    finally { if (generation === this.generation) { this.busy.set(null); if (guard.current()) this.focusPanel(generation); } guard.dispose(); }
  }
  protected chooseJob(record: Job): void {
    if (!this.canAct() || this.busy() || this.request()) return;
    this.clearTimer(); this.preview.set(null); this.previewContext = null; this.stopTarget.set(null); this.job.set(record);
    this.problems.set(null); this.problemsError.set(false);
    void this.readJob(record.job_id);
  }
  protected async readJob(id: string): Promise<void> {
    if (!this.canAct() || this.busy()) return;
    if (this.request() && !this.current(this.request()!)) { this.reset(true); return; }
    this.clearTimer(); this.busy.set('read'); this.error.set(false);
    const generation = this.generation, guard = this.capture();
    try {
      const result = await firstValueFrom(this.api.get<Job>(`/scan/faces/jobs/${id}`));
      if (!guard.current()) return;
      if (result.job_id !== id) throw new Error('Mismatched face update receipt');
      this.request.set(null); this.preview.set(null); this.previewContext = null; this.job.set(result); this.stopUncertain.set(false); this.updateHistory(result); this.armPoll();
      if (result.stop_requested || (result.state !== 'queued' && result.state !== 'running')) this.stopTarget.set(null);
    } catch { if (guard.current()) this.error.set(true); }
    finally { if (generation === this.generation) this.busy.set(null); guard.dispose(); }
  }
  private updateHistory(record: Job): void { this.history.update(rows => [record, ...rows.filter(row => row.job_id !== record.job_id)].slice(0, 10)); }
  protected async readProblems(after?: string | null): Promise<void> {
    const job = this.job();
    if (!job || !this.canAct() || this.busy() || (after && after !== this.problems()?.next_after)) return;
    this.clearTimer(); this.busy.set('read'); this.problemsError.set(false);
    const generation = this.generation, guard = this.capture();
    try {
      const page = await firstValueFrom(this.api.get<Problems>(`/scan/faces/jobs/${job.job_id}/items`, { limit: 48, ...(after ? { after } : {}) }));
      if (!guard.current() || this.job()?.job_id !== job.job_id) return;
      this.problems.set({ ...page, items: after ? [...(this.problems()?.items ?? []), ...page.items] : page.items });
      afterNextRender(() => { if (generation === this.generation && this.canAct() && this.job()?.job_id === job.job_id) this.problemsPanel()?.nativeElement.focus(); }, { injector: this.injector });
    } catch { if (guard.current()) this.problemsError.set(true); }
    finally { if (generation === this.generation) { this.busy.set(null); if (guard.current()) this.armPoll(); } guard.dispose(); }
  }
  protected review(): void { if (this.canAct() && !this.busy() && !this.active()) this.reviewRequested.emit(); }
  private armPoll(): void {
    this.clearTimer();
    const job = this.job();
    const generation = this.generation;
    if (job && this.active() && job.controlled_by_worker && this.canAct()) this.timer = setTimeout(() => {
      if (generation !== this.generation || this.job()?.job_id !== job.job_id || !this.active() || !this.canAct()) return;
      this.timer = null; void this.readJob(job.job_id);
    }, 2000);
  }
  protected async stop(): Promise<void> {
    const id = this.stopTarget();
    if (!id || id !== this.job()?.job_id || !this.active() || !this.canAct() || this.busy() || this.stopUncertain()) return;
    this.clearTimer(); this.busy.set('stop'); this.error.set(false);
    const generation = this.generation, guard = this.capture();
    try {
      const result = await firstValueFrom(this.api.post<Job>(`/scan/faces/jobs/${id}/cancel`, { job_id: id, confirm: true }));
      if (!guard.current()) return;
      if (result.job_id !== id) throw new Error('Mismatched face update receipt');
      this.job.set(result); this.stopTarget.set(null); this.updateHistory(result); this.armPoll();
    } catch { if (guard.current()) { this.error.set(true); this.stopUncertain.set(true); this.stopTarget.set(null); } }
    finally { if (generation === this.generation) { this.busy.set(null); if (guard.current()) this.focusPanel(generation); } guard.dispose(); }
  }
}
