import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { ActivityEntry, AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { GalleryStore } from '../gallery/gallery.store';
import { ActivityToolLabelPipe } from '../../shared/pipes/activity-tool-label.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

const CLOCK_MS = 15000;

/**
 * Header chip: "Assistant active" for a few seconds after any assistant event. Clicking it opens
 * the activity log, newest first; an entry that changed a known set of photos can show them.
 * It stays rendered while its panel is open, so the panel never vanishes under the pointer.
 */
@Component({
  selector: 'app-assistant-activity-chip',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatMenuModule, TranslatePipe, ActivityToolLabelPipe, RelativeTimePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'inline-flex' },
  template: `
    @if (changes.active() || open()) {
      <button
        mat-stroked-button
        type="button"
        class="!h-8 !px-2 min-[1700px]:!px-3 !text-xs gap-1 !min-w-0"
        data-testid="assistant-chip"
        [matMenuTriggerFor]="panel"
        [attr.aria-label]="I18N.assistant_activity.chip | translate"
        (menuOpened)="onOpened()"
        (menuClosed)="onClosed()"
      >
        <mat-icon class="!text-base !w-4 !h-4 !leading-4">smart_toy</mat-icon>
        <span class="hidden min-[1700px]:inline">{{ I18N.assistant_activity.chip | translate }}</span>
      </button>
    }
    <mat-menu #panel="matMenu" xPosition="before">
      <div class="px-4 py-2 text-sm font-medium" role="presentation">{{ I18N.assistant_activity.title | translate }}</div>
      @for (entry of changes.activity(); track entry.id) {
        @let label = (entry.tool | activityToolLabel: entry.kind) || (I18N.assistant_activity.unknown_tool | translate);
        <div class="px-4 py-2 text-sm flex flex-col gap-1 max-w-80" data-testid="activity-entry">
          <div class="flex items-baseline gap-2">
            <span class="font-medium truncate" data-testid="activity-label">{{ label }}</span>
            @if (entry.count !== null) {
              <span class="opacity-70 shrink-0">{{ (entry.count === 1 ? I18N.assistant_activity.photo_one : I18N.assistant_activity.photo_other) | translate: { count: entry.count } }}</span>
            }
            <span class="ml-auto text-[var(--mat-sys-on-surface-variant)] text-xs shrink-0">{{ entry.at | relativeTime: now() : i18n.locale() }}</span>
          </div>
          @if ((entry.showPaths ?? entry.paths)?.length) {
            <button mat-menu-item type="button" data-testid="activity-show" [attr.aria-label]="(I18N.assistant_activity.show_photos | translate) + ': ' + label" (click)="show(entry)">
              <mat-icon>photo_library</mat-icon>
              {{ I18N.assistant_activity.show_photos | translate }}
            </button>
          }
        </div>
      } @empty {
        <div class="px-4 py-2 text-sm text-[var(--mat-sys-on-surface-variant)]" data-testid="activity-empty">{{ I18N.assistant_activity.empty | translate }}</div>
      }
    </mat-menu>
  `,
})
export class AssistantActivityChipComponent {
  protected readonly changes = inject(AssistantChangesService);
  protected readonly i18n = inject(I18nService);
  private readonly gallery = inject(GalleryStore);
  private readonly router = inject(Router);
  protected readonly I18N = I18N;
  protected readonly open = signal(false);
  protected readonly now = signal(Date.now());
  private clock: ReturnType<typeof setInterval> | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopClock());
  }

  protected onOpened(): void {
    this.open.set(true);
    this.now.set(Date.now());
    this.stopClock();
    this.clock = setInterval(() => this.now.set(Date.now()), CLOCK_MS);
  }

  protected onClosed(): void {
    this.open.set(false);
    this.stopClock();
  }

  protected async show(entry: ActivityEntry): Promise<void> {
    const paths = entry.showPaths ?? entry.paths;
    if (!paths?.length) return;
    const path = this.router.url.split(/[?#]/)[0];
    if (path !== '/' && !path.startsWith('/album/')) await this.router.navigate(['/']);
    await this.gallery.showPaths(paths);
  }

  private stopClock(): void {
    if (this.clock !== null) clearInterval(this.clock);
    this.clock = null;
  }
}
