import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { TranslatePipe } from '../../pipes/translate.pipe';

interface ShortcutRow {
  keys: string[];
  labelKey: string;
}

interface ShortcutSection {
  titleKey: string;
  rows: ShortcutRow[];
}

/** Keyboard shortcuts reference, opened globally with '?'. */
@Component({
  selector: 'app-shortcuts-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title>{{ 'shortcuts.title' | translate }}</h2>
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
      <button mat-button mat-dialog-close>{{ 'shortcuts.close' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ShortcutsDialogComponent {
  protected readonly sections: ShortcutSection[] = [
    {
      titleKey: 'shortcuts.section_gallery',
      rows: [
        { keys: ['←', '→', '↑', '↓'], labelKey: 'shortcuts.navigate' },
        { keys: ['Enter'], labelKey: 'shortcuts.open_detail' },
        { keys: ['Space'], labelKey: 'shortcuts.toggle_select' },
        { keys: ['Ctrl', 'A'], labelKey: 'shortcuts.select_all' },
        { keys: ['1', '–', '5'], labelKey: 'shortcuts.rate' },
        { keys: ['0', 'X'], labelKey: 'shortcuts.reject' },
        { keys: ['F'], labelKey: 'shortcuts.favorite' },
        { keys: ['Esc'], labelKey: 'shortcuts.clear_selection' },
      ],
    },
    {
      titleKey: 'shortcuts.section_detail',
      rows: [
        { keys: ['←', '→'], labelKey: 'shortcuts.navigate' },
        { keys: ['Esc'], labelKey: 'shortcuts.close' },
      ],
    },
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
