import { createGalleryFilterContext } from './gallery-filter-context';
import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, signal, viewChild } from '@angular/core';
import { GalleryStore } from './gallery.store';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { parseScorePresence, serializeScorePresence, ScorePresenceMode, SCORE_PRESENCE_KEYS } from './score-presence.util';

@Component({
  selector: 'app-score-presence', imports: [TranslatePipe, MatIconModule], changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' }, template: `
    <details #disclosure (toggle)="expanded.set(disclosure.open)" class="border-b border-[var(--mat-sys-outline-variant)] mb-2 pb-2" [open]="!!store.filters().score_presence">
      <summary #summary class="cursor-pointer min-h-11 flex list-none items-center gap-2 text-sm font-medium">
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">fact_check</mat-icon>
        <span class="flex-1">{{ I18N.gallery.measurements.title | translate }}</span>
        @if (rows().length) { <span class="rounded-full bg-[var(--mat-sys-primary-container)] px-2 text-xs tabular-nums">{{ rows().length }}</span> }
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">{{ expanded() ? 'expand_less' : 'expand_more' }}</mat-icon>
      </summary>
      <p id="measurement-policy-help" class="my-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.measurements.help | translate }}</p>
      @if (policies(); as current) {
        <label for="measurement-policy-metric" class="block text-xs mt-2">{{ I18N.gallery.measurements.metric | translate }}</label>
        <select id="measurement-policy-metric" aria-describedby="measurement-policy-help" class="h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-sm"
                (change)="selected.set($any($event.target).value)">
          @for (metric of metrics(); track metric.minKey) { <option [value]="metric.minKey" [selected]="selectedKey() === metric.minKey">{{ metric.labelKey | translate }}</option> }
        </select>
        <label for="measurement-policy-mode" class="block text-xs mt-2">{{ I18N.gallery.measurements.policy | translate }}</label>
        <select id="measurement-policy-mode" aria-describedby="measurement-policy-help" class="h-11 w-full min-w-0 rounded border border-[var(--mat-sys-outline)] bg-[var(--mat-sys-surface)] px-2 text-sm"
                (change)="apply($any($event.target).value)">
          <option value="" [selected]="!current[selectedKey()]">{{ I18N.gallery.measurements.default | translate }}</option>
          @for (mode of modes; track mode.id) { <option [value]="mode.id" [selected]="current[selectedKey()] === mode.id">{{ mode.label | translate }}</option> }
        </select>
        @for (row of rows(); track row.key) {
          <p class="my-2 text-xs"><b>{{ row.label | translate }}</b>: {{ row.modeLabel | translate }}</p>
        }
      } @else { <p role="alert" class="text-xs">{{ I18N.gallery.measurements.invalid | translate }}</p> }
      @if (store.filters().score_presence) { <button type="button" class="min-h-11 underline text-xs" (click)="clear()">{{ I18N.gallery.measurements.clear | translate }}</button> }
    </details>
  `,
})
export class ScorePresenceComponent {
  readonly metrics = input.required<readonly { minKey: string; labelKey: string }[]>();
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly summary = viewChild<ElementRef<HTMLElement>>('summary');
  protected readonly selected = signal('');
  protected readonly expanded = signal(false);
  protected readonly selectedKey = computed(() => this.metrics().some(m => m.minKey === this.selected()) ? this.selected() : this.metrics()[0]?.minKey ?? '');
  protected readonly policies = computed(() => parseScorePresence(this.store.filters().score_presence ?? ''));
  protected readonly modes = [
    { id: 'include_missing', label: I18N.gallery.measurements.include_missing },
    { id: 'missing_only', label: I18N.gallery.measurements.missing_only },
    { id: 'measured_only', label: I18N.gallery.measurements.measured_only },
  ] as const;
  protected readonly rows = computed(() => Object.entries(this.policies() ?? {}).map(([key, mode]) => ({
    key, label: this.metrics().find(metric => metric.minKey === key)?.labelKey ?? key,
    modeLabel: I18N.gallery.measurements[mode],
  })));

  private readonly context = createGalleryFilterContext();

  protected apply(mode: string): void {
    const key = this.selectedKey();
    if (!this.context.current() || !SCORE_PRESENCE_KEYS.has(key) || (mode && !this.modes.some(row => row.id === mode))) return;
    const current = this.policies();
    if (!current) return;
    const next = { ...current };
    if (mode) next[key] = mode as ScorePresenceMode;
    else delete next[key];
    void this.store.updateFilter('score_presence', serializeScorePresence(next));
  }

  protected clear(): void {
    if (!this.context.current()) return;
    this.summary()?.nativeElement.focus();
    void this.store.updateFilter('score_presence', '');
  }
}
