import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, Injector, output, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ScanService, RecordedScanRun, ScanRetryPreview } from '../../core/services/scan.service';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';

@Component({
  selector: 'app-scan-history', imports: [DatePipe, TranslatePipe], changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' }, template: `
    <details data-scan-history class="mt-4 border-t border-[var(--mat-sys-outline-variant)] pt-2" (toggle)="onToggle($event)">
      <summary class="min-h-11 cursor-pointer text-sm font-medium">{{ I18N.scan.history.title | translate }}</summary>
      <p class="text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.scan.history.help | translate }}</p>
      <button type="button" class="min-h-11 underline text-xs" [disabled]="loading()" (click)="load(false)">{{ I18N.scan.history.refresh | translate }}</button>
      @if (loading()) { <p role="status" class="text-sm">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error()) { <p role="alert" class="text-sm">{{ I18N.scan.history.read_error | translate }}</p> }
      @if (loaded() && !loading() && !error() && !rows().length) { <p class="text-sm">{{ I18N.scan.history.empty | translate }}</p> }
      <ol class="m-0 p-0 list-none divide-y divide-[var(--mat-sys-outline-variant)]">
        @for (run of rows(); track run.id) {
          <li class="py-2 text-xs">
            <div class="flex flex-wrap gap-x-2 gap-y-1 font-medium"><span>#{{ run.id }}</span><span>{{ run.statusKey | translate }}</span><span class="min-w-0 [overflow-wrap:anywhere]">{{ run.mode }}</span></div>
            <p class="my-1">{{ run.started_at ? (run.started_at | date:'dd/MM/yyyy HH:mm':'UTC') : '—' }} · UTC</p>
            <p class="my-1">{{ I18N.scan.history.counts | translate:{ processed: run.processed_files ?? '—', total: run.total_files ?? '—', failed: run.failed_files ?? '—' } }}</p>
            @if (run.jobStatusKey; as pipelineState) {
              <details class="my-1">
                <summary class="min-h-11 cursor-pointer">{{ I18N.scan.history.pipeline | translate:{ state: (pipelineState | translate), phase: (run.jobPhaseKey ? (run.jobPhaseKey | translate) : '—') } }}</summary>
                @if (run.viewer_job_id) { <p class="my-1 [overflow-wrap:anywhere]">{{ I18N.scan.history.job_identity | translate }}: <code>{{ run.viewer_job_id }}</code></p> }
              </details>
            }
            @if (run.retained_failure_records) {
              <p class="my-1">{{ I18N.scan.history.retained | translate:{ count: run.retained_failure_records } }}</p>
              <ul class="m-0 ps-4">@for (stage of run.stages; track stage.stage) { <li>{{ stage.label | translate }}: {{ stage.count }}</li> }</ul>
              @if (run.retryable) {
                <button #retryTrigger type="button" class="min-h-11 underline" [disabled]="retryBusy() || submittedPlan() !== null" (click)="previewRetry(run.id, retryTrigger)">{{ I18N.scan.retry.preview | translate }}</button>
              }
            }
          </li>
        }
      </ol>
      @if (retryError(); as errorKey) { <p role="alert" class="text-sm">{{ errorKey | translate }}</p> }
      @if (retryBusy()) { <p role="status" class="text-sm">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (retryPreview(); as preview) {
        <section data-retry-preview tabindex="-1" class="mt-2 border border-[var(--mat-sys-outline-variant)] rounded p-3 text-sm" [attr.aria-label]="I18N.scan.retry.title | translate" (keydown.escape)="closeRetry($event)">
          <h3 class="mt-0 text-sm font-medium">{{ I18N.scan.retry.scope | translate:{ run: preview.run_id, count: preview.files.length } }}</h3>
          <p class="text-xs">{{ I18N.scan.retry.boundary | translate }}</p>
          @for (omission of retryOmissions(); track omission.reason) { <p class="my-1 text-xs">{{ omission.label | translate }}: {{ omission.count }}</p> }
          <details class="my-2">
            <summary class="min-h-11 cursor-pointer">{{ I18N.scan.retry.files | translate:{ count: preview.files.length } }}</summary>
            <ul class="max-h-48 overflow-y-auto text-xs ps-4 [overflow-wrap:anywhere]">@for (path of visibleRetryFiles(); track path) { <li>{{ path }}</li> }</ul>
            @if (visibleRetryFiles().length < preview.files.length) { <button type="button" class="min-h-11 underline" (click)="visibleFiles.update(moreFiles)">{{ I18N.scan.retry.more_files | translate }}</button> }
          </details>
          <p class="text-xs">{{ I18N.scan.retry.expiry | translate }}</p>
          <div class="flex flex-wrap gap-2">
            <button type="button" class="min-h-11 px-3 border rounded" [disabled]="retryBusy()" (click)="cancelRetry(true)">{{ I18N.ui.buttons.cancel | translate }}</button>
            <button type="button" class="min-h-11 px-3 bg-[var(--mat-sys-primary)] text-[var(--mat-sys-on-primary)] rounded" [disabled]="retryBusy()" (click)="applyRetry()">{{ I18N.scan.retry.apply | translate }}</button>
          </div>
        </section>
      }
      @if (submittedPlan()) {
        <p role="status" class="text-sm">{{ I18N.scan.retry.submitted | translate }}</p>
        <button type="button" class="min-h-11 underline text-sm" [disabled]="retryBusy()" (click)="readRetryReceipt()">{{ I18N.scan.retry.read_receipt | translate }}</button>
      }
      @if (nextBefore()) { <button type="button" class="min-h-11 underline text-xs" [disabled]="loading()" (click)="load(true)">{{ I18N.scan.history.older | translate }}</button> }
    </details>
  `,
})
export class ScanHistoryComponent {
  readonly retrySubmitted = output<void>();
  readonly retryAccepted = output<string>();
  protected readonly I18N = I18N;
  private readonly scan = inject(ScanService);
  private readonly auth = inject(AuthService);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  private retryTrigger: HTMLButtonElement | null = null;
  private readonly records = signal<RecordedScanRun[]>([]);
  protected readonly nextBefore = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal(false);
  protected readonly loaded = signal(false);
  private generation = 0;
  private context: ReturnType<StalenessGuardFactory['create']> | null = null;
  private retryContext: ReturnType<StalenessGuardFactory['create']> | null = null;
  private retryEpoch = 0;
  private expiry: ReturnType<typeof setTimeout> | null = null;
  protected readonly retryPreview = signal<ScanRetryPreview | null>(null);
  protected readonly retryBusy = signal(false);
  protected readonly retryError = signal<string | null>(null);
  protected readonly submittedPlan = signal<string | null>(null);
  protected readonly visibleFiles = signal(20);
  protected readonly moreFiles = (count: number) => count + 20;
  protected readonly visibleRetryFiles = computed(() => this.retryPreview()?.files.slice(0, this.visibleFiles()) ?? []);
  protected readonly retryOmissions = computed(() => this.retryPreview()?.omissions.map(item => ({
    ...item, label: I18N.scan.retry.omissions[item.reason],
  })) ?? []);
  private readonly states: Record<string, string> = I18N.scan.history.states;
  protected readonly rows = computed(() => this.records().map(run => ({
    ...run,
    retryable: ['completed', 'interrupted', 'failed'].includes(run.status),
    jobStatusKey: run.job_status ? this.states[run.job_status] ?? I18N.scan.history.unknown : null,
    jobPhaseKey: run.job_phase ? (I18N.scan.phase as Record<string, string>)[run.job_phase] ?? null : null,
    statusKey: run.status === 'completed' && ((run.failed_files ?? 0) > 0 || run.retained_failure_records > 0)
      ? I18N.scan.history.completed_failures : this.states[run.status] ?? I18N.scan.history.unknown,
    stages: run.failure_stages.map(stage => ({ ...stage, label: (I18N.scan.history.stages as Record<string, string>)[stage.stage] ?? I18N.scan.history.stages.other })),
  })));

  constructor() {
    effect(() => {
      this.auth.identity(); this.auth.status(); this.scan.canLaunch();
      this.cancel(); this.records.set([]); this.nextBefore.set(null); this.error.set(false); this.loaded.set(false);
      this.cancelRetry();
    });
    this.destroyRef.onDestroy(() => { this.cancel(); this.cancelRetry(); });
  }

  private cancel(): void {
    this.generation++; this.context?.dispose(); this.context = null; this.loading.set(false);
  }

  protected onToggle(event: Event): void {
    if (event.target !== event.currentTarget) return;
    if ((event.target as HTMLDetailsElement).open) { if (!this.loading()) void this.load(false); }
    else { this.cancel(); if (!this.submittedPlan()) this.cancelRetry(); }
  }

  protected cancelRetry(restoreFocus = false): void {
    if (restoreFocus && this.retryContext?.current() && this.retryTrigger?.isConnected) this.retryTrigger.focus();
    this.retryEpoch++;
    this.retryContext?.dispose(); this.retryContext = null;
    if (this.expiry) clearTimeout(this.expiry);
    this.expiry = null;
    this.retryPreview.set(null); this.retryBusy.set(false); this.submittedPlan.set(null); this.retryError.set(null);
  }

  protected closeRetry(event: Event): void {
    if (this.retryBusy()) return;
    event.stopPropagation(); event.preventDefault(); this.cancelRetry(true);
  }

  private retryGuard(): ReturnType<StalenessGuardFactory['create']> {
    this.retryContext?.dispose();
    const token = this.auth.token;
    const guard = this.guards.create(this.destroyRef, {
      requireEdition: false, track: 'status', valid: () => this.scan.canLaunch() && this.auth.token === token,
      onNavigate: () => this.cancelRetry(),
    });
    this.retryContext = guard;
    return guard;
  }

  protected async previewRetry(runId: number, trigger: HTMLButtonElement): Promise<void> {
    if (this.retryBusy() || this.submittedPlan()) return;
    this.cancelRetry();
    this.retryTrigger = trigger;
    const epoch = this.retryEpoch;
    const guard = this.retryGuard();
    if (!guard.current()) return;
    this.retryBusy.set(true);
    try {
      const preview = await this.scan.previewRetry(runId);
      if (epoch !== this.retryEpoch || !guard.current()) return;
      this.retryPreview.set(preview); this.visibleFiles.set(20);
      afterNextRender(() => {
        if (epoch === this.retryEpoch && guard.current() && this.retryPreview() === preview) {
          this.host.nativeElement.querySelector<HTMLElement>('[data-retry-preview]')?.focus();
        }
      }, { injector: this.injector });
      this.expiry = setTimeout(() => {
        if (epoch === this.retryEpoch && !this.submittedPlan()) {
          this.cancelRetry(); this.retryError.set(I18N.scan.retry.expired);
        }
      }, preview.expires_in_seconds * 1000);
    } catch {
      if (epoch === this.retryEpoch && guard.current()) this.retryError.set(I18N.scan.retry.preview_error);
    } finally {
      if (epoch === this.retryEpoch) this.retryBusy.set(false);
    }
  }

  protected async applyRetry(): Promise<void> {
    const preview = this.retryPreview();
    const guard = this.retryContext;
    if (!preview || this.retryBusy() || this.submittedPlan()) return;
    if (!guard?.current()) { this.cancelRetry(); return; }
    const epoch = this.retryEpoch;
    this.submittedPlan.set(preview.plan_id); this.retryPreview.set(null); this.retryBusy.set(true); this.retryError.set(null);
    if (this.expiry) clearTimeout(this.expiry);
    this.retrySubmitted.emit();
    try {
      const jobId = await this.scan.applyRetry(preview.plan_id);
      if (epoch === this.retryEpoch && guard.current() && jobId) this.retryAccepted.emit(jobId);
    } catch {
      if (epoch === this.retryEpoch && guard.current()) this.retryError.set(I18N.scan.retry.unconfirmed);
    } finally {
      if (epoch === this.retryEpoch) this.retryBusy.set(false);
    }
  }

  protected async readRetryReceipt(): Promise<void> {
    const id = this.submittedPlan();
    const guard = this.retryContext;
    if (!id || !guard?.current() || this.retryBusy()) return;
    const epoch = this.retryEpoch;
    this.retryBusy.set(true);
    try {
      const receipt = await this.scan.loadRetryReceipt(id);
      if (epoch !== this.retryEpoch || !guard.current()) return;
      if (receipt.state === 'spawned' && receipt.job_id) {
        this.retryAccepted.emit(receipt.job_id);
        this.retryError.set(null); await this.scan.connect(false);
      }
      else if (receipt.state === 'refused' || receipt.state === 'preview') {
        this.submittedPlan.set(null); this.retryError.set(I18N.scan.retry.not_started);
      }
    } catch {
      if (epoch === this.retryEpoch && guard.current()) this.retryError.set(I18N.scan.retry.unconfirmed);
    } finally {
      if (epoch === this.retryEpoch) this.retryBusy.set(false);
    }
  }

  protected async load(older: boolean): Promise<void> {
    if (this.loading() || (older && !this.nextBefore())) return;
    this.cancel();
    const generation = this.generation;
    const token = this.auth.token;
    const context = this.guards.create(this.destroyRef, { requireEdition: false, track: 'status', valid: () => this.auth.token === token && this.scan.canLaunch() });
    this.context = context;
    if (!context.current()) { context.dispose(); return; }
    this.loading.set(true); this.error.set(false);
    try {
      const result = await this.scan.loadHistory(older ? this.nextBefore()! : undefined);
      if (generation !== this.generation || !context.current()) return;
      this.records.update(previous => older ? [...previous, ...result.runs] : result.runs);
      this.nextBefore.set(result.next_before ?? null); this.loaded.set(true);
    } catch {
      if (generation === this.generation && context.current()) this.error.set(true);
    } finally {
      context.dispose();
      if (generation === this.generation) { this.loading.set(false); this.context = null; }
    }
  }
}
