import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { i18nKeys } from '../../../core/i18n/keys';
import { galleryShortcutSection, photoShortcutSection, ShortcutSection } from '../../../features/gallery/gallery-shortcuts';
import { KeyboardMappingService } from '../../../core/services/keyboard-mapping.service';

/** Keyboard shortcuts reference, opened globally with '?'. */
@Component({
  selector: 'app-shortcuts-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, TranslatePipe],
  // Same title-row phantom flex item as the other dialogs: neutralise the
  // Material title's content:"" ::before so the row gap lands correctly.
  styles: `
    h2[mat-dialog-title]::before {
      content: none;
    }
  `,

  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-6 !pt-5 !pb-4 before:content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">keyboard</mat-icon>
      </span>
      {{ I18N.shortcuts.title | translate }}
    </h2>
    <mat-dialog-content>
      <div class="flex flex-col gap-4 min-w-[320px]">
        @for (section of sections; track section.titleKey) {
          <div>
            <h3 class="text-sm font-semibold opacity-70 mb-2">{{ section.titleKey | translate }}</h3>
            <div class="flex flex-col gap-1.5">
              @for (row of section.rows; track row.labelKey) {
                <div class="flex items-center justify-between gap-4 text-sm">
                  <span>{{ row.labelKey | translate }}</span>
                  <span class="flex gap-1 shrink-0">
                    @for (key of row.keys; track key) {
                      <kbd class="px-1.5 py-0.5 rounded border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-high)] text-xs font-mono">{{ key }}</kbd>
                    } @empty {
                      {{ I18N.shortcuts.unassigned | translate }}
                    }
                  </span>
                </div>
              }
            </div>
          </div>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.shortcuts.close | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ShortcutsDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly keymap = inject(KeyboardMappingService);

  /** Built at open time from the live key mapping, so a remapped key shows
   *  here the moment it is saved. */
  protected readonly sections: ShortcutSection[] = [
    galleryShortcutSection(this.keymap.keymap()),
    photoShortcutSection(this.keymap.keymap()),
    {
      titleKey: 'shortcuts.section_comparison',
      rows: [
        { keys: ['A'], labelKey: 'shortcuts.comp_left_wins' },
        { keys: ['B'], labelKey: 'shortcuts.comp_right_wins' },
        { keys: ['T'], labelKey: 'comparison.tie' },
        { keys: ['S'], labelKey: 'comparison.skip' },
      ],
    },
    {
      titleKey: 'shortcuts.section_global',
      rows: [
        { keys: ['?'], labelKey: 'shortcuts.show_help' },
      ],
    },
  ];
}
