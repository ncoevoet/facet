import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../../core/i18n/keys';
import type { PageHelpNote } from '../../../core/services/page-help.service';
import type { CullingShortcutRow } from '../../../features/gallery/culling-shortcuts';

interface ShortcutSection { titleKey: string; rows: CullingShortcutRow[]; }

interface HelpDialogData { key?: string | null; note?: PageHelpNote | null; shortcutSections?: ShortcutSection[]; }

/** The user menu's Help dialog: the current page's help text in a proper
 *  modal, instead of toggling the in-page banner — a menu affordance that
 *  opens a banner reads as a misfire. On the gallery and culling routes the
 *  dialog also carries that page's keyboard reference, which used to live
 *  only in the in-page banners. */
@Component({
  selector: 'app-help-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !text-base !font-semibold !m-0 !px-6 !pt-5 !mb-3 before:!content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">help_outline</mat-icon>
      </span>
      {{ I18N.nav.help | translate }}
    </h2>
    <mat-dialog-content class="!px-6">
      @if (descriptionKey; as key) {
        <ul class="m-0 pl-0 list-none flex flex-col gap-2.5 mb-1">
          @for (line of (key | translate).split('\n'); track $index) {
            <li class="flex items-start gap-2.5 text-sm leading-relaxed">
              <span class="mt-[7px] w-1.5 h-1.5 rounded-full bg-[var(--mat-sys-primary)] shrink-0" aria-hidden="true"></span>
              <span>{{ line }}</span>
            </li>
          }
        </ul>
      } @else {
        <p class="text-sm leading-relaxed m-0 opacity-70">{{ I18N.gallery.help_none | translate }}</p>
      }
      @if (note; as n) {
        <p class="text-xs opacity-70 mt-3 mb-0">{{ n.key | translate:(n.params ?? {}) }}</p>
      }
      @if (shortcutSections.length) {
        <div class="mt-4 pt-3 border-t border-[var(--mat-sys-outline-variant)] flex flex-wrap gap-x-10 gap-y-3">
          @for (section of shortcutSections; track section.titleKey) {
            <div>
              <div class="text-xs font-semibold uppercase opacity-50 mb-1.5">{{ section.titleKey | translate }}</div>
              <div class="space-y-1">
                @for (row of section.rows; track row.labelKey) {
                  <div class="flex items-center gap-2 text-xs">
                    <span class="flex gap-1">
                      @for (k of row.keys; track k) {
                        <kbd class="px-1.5 py-0.5 rounded border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container-high)] text-xs font-mono">{{ k }}</kbd>
                      } @empty {
                        {{ I18N.shortcuts.unassigned | translate }}
                      }
                    </span>
                    <span class="opacity-80">{{ row.labelKey | translate }}</span>
                  </div>
                }
              </div>
            </div>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions class="!px-6 !pb-5">
      <span class="flex-1"></span>
      <button mat-flat-button color="primary" mat-dialog-close class="!rounded-lg !px-5">
        {{ I18N.dialog.ok | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class HelpDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly data = inject(MAT_DIALOG_DATA) as HelpDialogData;
  /** Set by the opener from PageHelpService before open(); the opener also
   *  resolves the keyboard sections for the current route (the dialog cannot
   *  trust its own constructor timing for router state). */
  readonly descriptionKey = this.data.key ?? null;
  readonly note = this.data.note ?? null;
  readonly shortcutSections: ShortcutSection[] = this.data.shortcutSections ?? [];
}
