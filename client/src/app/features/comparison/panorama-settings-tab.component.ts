import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';

import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PanoramaSettingsService, PanoramaSettings } from './panorama-settings.service';

/**
 * The panorama detector's thresholds.
 *
 * Only the four that were actually calibrated against labelled sets are given
 * their own control; the rest of the block is left to the config file, since
 * exposing seventeen numbers invites tuning the ones nobody has evidence for.
 *
 * Saving does NOT relabel anything: detection is a batch pass over the library,
 * not a live query, so the re-run is offered next to the save rather than
 * leaving the user to wonder why the gallery has not changed.
 */
@Component({
  selector: 'app-panorama-settings-tab',
  standalone: true,
  imports: [
    FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressSpinnerModule, MatSlideToggleModule, MatTooltipModule, TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block p-4' },
  template: `
    @if (loading()) {
      <div class="flex justify-center p-8"><mat-spinner diameter="32" /></div>
    } @else if (settings(); as s) {
      <p class="text-sm opacity-70 mb-4 max-w-3xl">
        {{ I18N.panorama.settings.intro | translate }}
      </p>

      <div class="flex flex-col gap-4 max-w-md">
        <mat-slide-toggle [(ngModel)]="s.enabled">
          {{ I18N.panorama.settings.enabled | translate }}
        </mat-slide-toggle>

        <mat-form-field>
          <mat-label>{{ I18N.panorama.settings.min_frames | translate }}</mat-label>
          <input matInput type="number" min="2" max="200" step="1" [(ngModel)]="s.min_frames">
          <mat-hint>{{ I18N.panorama.settings.min_frames_hint | translate }}</mat-hint>
        </mat-form-field>

        <mat-form-field>
          <mat-label>{{ I18N.panorama.settings.min_drift | translate }}</mat-label>
          <input matInput type="number" min="0.05" max="10" step="0.01" [(ngModel)]="s.min_drift">
          <mat-hint>{{ I18N.panorama.settings.min_drift_hint | translate }}</mat-hint>
        </mat-form-field>

        <mat-form-field>
          <mat-label>{{ I18N.panorama.settings.max_gap_seconds | translate }}</mat-label>
          <input matInput type="number" min="1" max="600" step="1" [(ngModel)]="s.max_gap_seconds">
          <mat-hint>{{ I18N.panorama.settings.max_gap_hint | translate }}</mat-hint>
        </mat-form-field>

        <mat-form-field>
          <mat-label>{{ I18N.panorama.settings.hdr_span | translate }}</mat-label>
          <input matInput type="number" min="0.1" max="10" step="0.1" [(ngModel)]="s.hdr_min_span_stops">
          <mat-hint>{{ I18N.panorama.settings.hdr_span_hint | translate }}</mat-hint>
        </mat-form-field>
      </div>

      <div class="flex items-center gap-3 mt-6">
        <button mat-flat-button [disabled]="saving()" (click)="save()">
          <mat-icon>save</mat-icon>{{ I18N.panorama.settings.save | translate }}
        </button>
        <button mat-stroked-button [disabled]="detecting()" (click)="redetect()"
                [matTooltip]="I18N.panorama.settings.redetect_tooltip | translate">
          <mat-icon>refresh</mat-icon>{{ I18N.panorama.settings.redetect | translate }}
        </button>
        @if (detecting()) { <mat-spinner diameter="20" /> }
      </div>

      @if (message(); as m) {
        <p class="mt-4 text-sm" [class.text-red-500]="failed()">{{ m }}</p>
      }
    }
  `,
})
export class PanoramaSettingsTabComponent {
  protected readonly I18N = I18N;
  private readonly service = inject(PanoramaSettingsService);

  protected readonly settings = signal<PanoramaSettings | null>(null);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly detecting = signal(false);
  protected readonly message = signal('');
  protected readonly failed = signal(false);

  constructor() {
    this.service.load().subscribe({
      next: s => { this.settings.set(s); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  protected save(): void {
    const current = this.settings();
    if (!current) return;
    this.saving.set(true);
    this.failed.set(false);
    this.service.save(current).subscribe({
      next: r => {
        this.saving.set(false);
        this.message.set(r.message ?? '');
      },
      error: e => {
        this.saving.set(false);
        this.failed.set(true);
        this.message.set(e?.error?.detail ?? 'Save failed');
      },
    });
  }

  protected redetect(): void {
    this.detecting.set(true);
    this.failed.set(false);
    this.service.redetect().subscribe({
      next: r => { this.detecting.set(false); this.message.set(r.message ?? ''); },
      error: e => {
        this.detecting.set(false);
        this.failed.set(true);
        this.message.set(e?.error?.detail ?? 'Could not start detection');
      },
    });
  }
}
