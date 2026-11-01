import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ScanService, RecordedScanRun } from '../../core/services/scan.service';
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
            @if (run.retained_failure_records) {
              <p class="my-1">{{ I18N.scan.history.retained | translate:{ count: run.retained_failure_records } }}</p>
              <ul class="m-0 ps-4">@for (stage of run.stages; track stage.stage) { <li>{{ stage.label | translate }}: {{ stage.count }}</li> }</ul>
            }
          </li>
        }
      </ol>
      @if (nextBefore()) { <button type="button" class="min-h-11 underline text-xs" [disabled]="loading()" (click)="load(true)">{{ I18N.scan.history.older | translate }}</button> }
    </details>
  `,
})
export class ScanHistoryComponent {
  protected readonly I18N = I18N;
  private readonly scan = inject(ScanService);
  private readonly auth = inject(AuthService);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly records = signal<RecordedScanRun[]>([]);
  protected readonly nextBefore = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal(false);
  protected readonly loaded = signal(false);
  private generation = 0;
  private context: ReturnType<StalenessGuardFactory['create']> | null = null;
  private readonly states: Record<string, string> = I18N.scan.history.states;
  protected readonly rows = computed(() => this.records().map(run => ({
    ...run,
    statusKey: run.status === 'completed' && ((run.failed_files ?? 0) > 0 || run.retained_failure_records > 0)
      ? I18N.scan.history.completed_failures : this.states[run.status] ?? I18N.scan.history.unknown,
    stages: run.failure_stages.map(stage => ({ ...stage, label: (I18N.scan.history.stages as Record<string, string>)[stage.stage] ?? I18N.scan.history.stages.other })),
  })));

  constructor() {
    effect(() => {
      this.auth.identity(); this.auth.status(); this.scan.canLaunch();
      this.cancel(); this.records.set([]); this.nextBefore.set(null); this.error.set(false); this.loaded.set(false);
    });
    this.destroyRef.onDestroy(() => this.cancel());
  }

  private cancel(): void {
    this.generation++; this.context?.dispose(); this.context = null; this.loading.set(false);
  }

  protected onToggle(event: Event): void {
    if ((event.target as HTMLDetailsElement).open) { if (!this.loading()) void this.load(false); }
    else this.cancel();
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
