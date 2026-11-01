import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, ElementRef, inject, input, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { GalleryStore } from './gallery.store';
import { AuthService } from '../../core/services/auth.service';
import { StalenessGuardFactory } from '../../core/services/staleness-guard.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { parseScorePresence, serializeScorePresence, ScorePresenceMode, SCORE_PRESENCE_KEYS } from './score-presence.util';

@Component({
  selector: 'app-score-presence', imports: [TranslatePipe], changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' }, template: `
    <details class="border-b border-[var(--mat-sys-outline-variant)] mb-2 pb-2" [open]="!!store.filters().score_presence">
      <summary #summary class="cursor-pointer min-h-11 flex items-center text-sm font-medium">{{ I18N.gallery.measurements.title | translate }}</summary>
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
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly guards = inject(StalenessGuardFactory);
  private readonly destroyRef = inject(DestroyRef);
  private readonly summary = viewChild<ElementRef<HTMLElement>>('summary');
  private session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
  private context = this.newContext();
  private readonly path = signal(this.router.url.split('?')[0]);
  private readonly pending = signal(false);
  private navigationId = 0;
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

  constructor() {
    effect(() => {
      this.auth.identity(); this.auth.status();

      this.refreshContext(true);
    });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        if (event.id < this.navigationId) return;
        this.navigationId = event.id; this.pending.set(true);
      } else if (event instanceof NavigationEnd || event instanceof NavigationSkipped || event instanceof NavigationError || event instanceof NavigationCancel) {
        if (event.id < this.navigationId) return;
        if (event instanceof NavigationCancel && (event.code === NavigationCancellationCode.Redirect || event.code === NavigationCancellationCode.SupersededByNewNavigation)) return;
        this.navigationId = event.id;
        this.path.set((event instanceof NavigationEnd ? event.urlAfterRedirects : this.router.url).split('?')[0]);
        this.pending.set(false); this.refreshContext();
      }
    });
  }

  private newContext() {
    const token = this.auth.token;
    return this.guards.create(this.destroyRef, { requireEdition: false, track: 'status', valid: () => this.auth.token === token });
  }

  private refreshContext(authChanged = false): void {
    if (!authChanged && (this.session.owner !== this.auth.identity() || this.session.status !== this.auth.status() || this.session.token !== this.auth.token)) return;
    this.context.dispose();
    this.session = { owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token };
    this.context = this.newContext();
  }

  private current(): boolean { return !this.pending() && (this.path() === '/' || /^\/album\/\d+$/.test(this.path())) && this.context.current(); }

  protected apply(mode: string): void {
    const key = this.selectedKey();
    if (!this.current() || !SCORE_PRESENCE_KEYS.has(key) || (mode && !this.modes.some(row => row.id === mode))) return;
    const current = this.policies();
    if (!current) return;
    const next = { ...current };
    if (mode) next[key] = mode as ScorePresenceMode;
    else delete next[key];
    void this.store.updateFilter('score_presence', serializeScorePresence(next));
  }

  protected clear(): void {
    if (!this.current()) return;
    this.summary()?.nativeElement.focus();
    void this.store.updateFilter('score_presence', '');
  }
}
