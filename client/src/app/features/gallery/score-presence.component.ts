import { createGalleryFilterContext } from './gallery-filter-context';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, inject, Injector, input, signal, viewChild } from '@angular/core';
import { GalleryStore } from './gallery.store';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelect, MatSelectModule } from '@angular/material/select';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { parseScorePresence, serializeScorePresence, ScorePresenceMode, SCORE_PRESENCE_KEYS } from './score-presence.util';

/** The body of the filter sidebar's "Measurement availability" section; the sidebar owns its expansion panel. */
@Component({
  selector: 'app-score-presence', imports: [TranslatePipe, MatButtonModule, MatFormFieldModule, MatIconModule, MatSelectModule], changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col gap-2 pb-2' }, template: `
    <p id="measurement-policy-help" class="m-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.measurements.help | translate }}</p>
    @if (policies(); as current) {
      <mat-form-field subscriptSizing="dynamic" class="w-full">
        <mat-label>{{ I18N.gallery.measurements.metric | translate }}</mat-label>
        <mat-select id="measurement-policy-metric" aria-describedby="measurement-policy-help" [value]="selectedKey()" (selectionChange)="selected.set($event.value)">
          @for (metric of metrics(); track metric.minKey) { <mat-option [value]="metric.minKey">{{ metric.labelKey | translate }}</mat-option> }
        </mat-select>
      </mat-form-field>
      <mat-form-field subscriptSizing="dynamic" class="w-full">
        <mat-label>{{ I18N.gallery.measurements.policy | translate }}</mat-label>
        <mat-select #modeSelect id="measurement-policy-mode" aria-describedby="measurement-policy-help" [value]="current[selectedKey()] ?? ''" (selectionChange)="apply($event.value)">
          <mat-option value="">{{ I18N.gallery.measurements.default | translate }}</mat-option>
          @for (mode of modes; track mode.id) { <mat-option [value]="mode.id">{{ mode.label | translate }}</mat-option> }
        </mat-select>
      </mat-form-field>
      @if (rows().length) {
        <ul class="m-0 flex list-none flex-col gap-1 p-0 px-1 text-xs">
          @for (row of rows(); track row.key) {
            <li><span class="font-medium">{{ row.label | translate }}</span> · <span class="text-[var(--mat-sys-on-surface-variant)]">{{ row.modeLabel | translate }}</span></li>
          }
        </ul>
      }
    } @else { <p role="alert" class="m-0 text-xs">{{ I18N.gallery.measurements.invalid | translate }}</p> }
    @if (store.filters().score_presence) {
      <button type="button" mat-stroked-button data-clear-measurements class="w-full" (click)="clear()">
        <mat-icon>close</mat-icon>
        {{ I18N.gallery.measurements.clear | translate }}
      </button>
    }
  `,
})
export class ScorePresenceComponent {
  readonly metrics = input.required<readonly { minKey: string; labelKey: string }[]>();
  protected readonly I18N = I18N;
  protected readonly store = inject(GalleryStore);
  private readonly modeSelect = viewChild<MatSelect>('modeSelect');
  private readonly injector = inject(Injector);
  protected readonly selected = signal('');
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
    const current = this.policies();
    if (!this.context.current() || !SCORE_PRESENCE_KEYS.has(key) || (mode && !this.modes.some(row => row.id === mode)) || !current) {
      // A refused choice must not stay displayed: the select shows the stored policy, not the click.
      const select = this.modeSelect();
      if (select) select.value = current?.[key] ?? '';
      return;
    }
    const next = { ...current };
    if (mode) next[key] = mode as ScorePresenceMode;
    else delete next[key];
    void this.store.updateFilter('score_presence', serializeScorePresence(next));
  }

  /** The clear button leaves the DOM with the policy, so focus moves to the policy select, which renders once the cleared policy parses. */
  protected async clear(): Promise<void> {
    if (!this.context.current()) return;
    await this.store.updateFilter('score_presence', '');
    afterNextRender(() => this.modeSelect()?.focus(), { injector: this.injector });
  }
}
