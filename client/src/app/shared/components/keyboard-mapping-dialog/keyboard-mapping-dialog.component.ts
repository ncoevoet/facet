import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../../shared/pipes/translate.pipe';
import { i18nKeys, I18N } from '../../../core/i18n/keys';
import { KEYMAP_ACTIONS, KeymapConfig, KeyboardMappingService } from '../../../core/services/keyboard-mapping.service';

/** Lets the user reassign the primary key of each gallery and photo-page
 *  action. Click a row to enter capture mode, press the new key; Esc or Tab
 *  backs out, and a key held by another action or a reserved key is refused
 *  with an inline message. Modifier combos and multi-character key names
 *  (arrows, Home, F-keys) leave capture armed. */
@Component({
  selector: 'app-keyboard-mapping-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-6 !pt-5 !pb-0 before:!content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">keyboard</mat-icon>
      </span>
      <span class="flex flex-col">
        <span class="!text-base !font-semibold">{{ I18N.shortcuts.keymap_title | translate }}</span>
        <span class="!text-xs !font-normal opacity-60 mt-0.5">{{ I18N.shortcuts.keymap_hint | translate }}</span>
      </span>
    </h2>
    <mat-dialog-content class="!px-6 !pb-1 !overflow-hidden">
      <div class="flex flex-col gap-0.5">
        @for (action of KEYMAP_ACTIONS; track action.id) {
          <button type="button" data-keymap-row
                  class="w-full flex items-center gap-3 px-2.5 py-1.5 rounded-lg text-left transition-colors hover:bg-[var(--mat-sys-surface-container)]"
                  [class.!bg-[var(--mat-sys-surface-container)]]="capturing() === action.id"
                  (click)="startCapture(action.id, $event)">
            <span class="flex-1 text-sm">{{ action.labelKey | translate }}</span>
            @if (capturing() === action.id) {
              <kbd class="px-2 py-1 rounded-md border border-[var(--mat-sys-primary)] bg-[var(--mat-sys-surface-container-high)] font-mono text-xs text-[var(--mat-sys-primary)] min-w-[3.5rem] text-center animate-pulse">
                {{ I18N.shortcuts.press_key | translate }}
              </kbd>
            } @else {
              <kbd class="px-2 py-1 rounded-md border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-high)] font-mono text-xs min-w-[3.5rem] text-center">
                @if (keyLabels()[action.id]) {
                  {{ keyLabels()[action.id] }}
                } @else {
                  {{ I18N.shortcuts.unassigned | translate }}
                }
              </kbd>
            }
          </button>
        }
      </div>
      <p role="status" class="text-xs text-[var(--mat-sys-error)] mb-0" [class.mt-2]="error()">
        @if (error(); as message) {
          {{ message | translate }}
        }
      </p>
    </mat-dialog-content>
    <mat-dialog-actions class="!px-6 !pb-5">
      <button mat-button (click)="resetAll()">{{ I18N.shortcuts.reset_keys | translate }}</button>
      <span class="flex-1"></span>
      <button mat-flat-button mat-dialog-close class="!rounded-lg !px-5">{{ I18N.dialog.ok | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class KeyboardMappingDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly KEYMAP_ACTIONS = KEYMAP_ACTIONS;
  private readonly mapping = inject(KeyboardMappingService);
  private readonly capturingAction = signal<keyof KeymapConfig | null>(null);
  private readonly errorMessage = signal('');
  protected readonly capturing = this.capturingAction.asReadonly();
  protected readonly error = this.errorMessage.asReadonly();
  protected readonly keyLabels = computed(() => {
    const map = this.mapping.keymap();
    return Object.fromEntries(KEYMAP_ACTIONS.map(a => [a.id, map[a.id].toUpperCase()])) as Record<keyof KeymapConfig, string>;
  });

  constructor() {
    // Capture phase on document: runs before the dialog overlay's Escape
    // handler on body and before page shortcuts (the photo page's Escape goes
    // back), so a key pressed while capturing reaches nothing else.
    const document = inject(DOCUMENT);
    const listener = (event: KeyboardEvent) => this.onKeydown(event);
    document.addEventListener('keydown', listener, true);
    inject(DestroyRef).onDestroy(() => document.removeEventListener('keydown', listener, true));
  }

  protected startCapture(action: keyof KeymapConfig, event: MouseEvent): void {
    event.stopPropagation();
    this.errorMessage.set('');
    this.capturingAction.set(action);
  }

  protected resetAll(): void {
    this.mapping.resetAll();
    this.errorMessage.set('');
    this.capturingAction.set(null);
  }

  private onKeydown(event: KeyboardEvent): void {
    const action = this.capturingAction();
    if (!action) return;
    if (event.key === 'Tab') {
      this.capturingAction.set(null);
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.key === 'Escape') {
      this.capturingAction.set(null);
      return;
    }
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    const refused = this.mapping.setKey(action, event.key);
    this.errorMessage.set(refused === 'reserved' ? I18N.shortcuts.key_reserved : refused === 'in_use' ? I18N.shortcuts.key_in_use : '');
    this.capturingAction.set(null);
  }
}
