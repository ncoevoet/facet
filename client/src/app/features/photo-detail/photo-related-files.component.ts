import { PhotoPanelReader } from './photo-panel-reader';
import { LogicalAssetApplied } from '../../shared/models/logical-asset-change';
import { PhotoLogicalAssetComponent } from './photo-logical-asset.component';
import { ChangeDetectionStrategy, Component, computed, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../core/i18n/keys';
import type { RelatedFilesResponse } from '../../core/api/types';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ContextHelpComponent } from '../../shared/components/context-help/context-help.component';

@Component({
  selector: 'app-photo-related-files',
  imports: [MatIconModule, TranslatePipe, ContextHelpComponent, PhotoLogicalAssetComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    <details [open]="expanded()" data-related-files (keydown.escape)="expanded() && close($event, trigger)" class="[&[open]>summary>mat-icon:last-child]:rotate-180">
      <summary #trigger (click)="toggle($event)" class="flex min-h-9 max-sm:min-h-11 cursor-pointer items-center gap-2 text-xs font-medium focus-visible:outline-2">
        <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">file_copy</mat-icon><h3 class="m-0 text-xs font-medium">{{ I18N.related_files.title | translate }}</h3>
        <mat-icon aria-hidden="true" class="ml-auto !h-5 !w-5 shrink-0 !text-xl transition-transform motion-reduce:transition-none">expand_more</mat-icon>
      </summary>
      @if (expanded()) {
        <div class="space-y-2 pb-2 text-xs">
          @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
          @else if (failed()) {
            <p role="alert">{{ I18N.related_files.failed | translate }}</p>
            <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
          } @else if (data(); as result) {
            <ul class="m-0 list-none space-y-2 p-0" [attr.aria-label]="I18N.related_files.title | translate">
              @for (file of rows(); track file.name) {
                <li class="flex min-w-0 items-start gap-2">
                  <mat-icon aria-hidden="true" class="!h-4 !w-4 shrink-0 !text-base">{{ file.icon }}</mat-icon>
                  <div class="min-w-0 flex-1">
                    <bdi class="block break-words font-medium">{{ file.name }}</bdi>
                    <span class="text-[var(--mat-sys-on-surface-variant)]">{{ file.kindLabel | translate }} · {{ file.stateLabel | translate }}</span>
                    @if (file.indexed && file.kind !== 'photo') { <span class="ml-1">· {{ I18N.related_files.indexed | translate }}</span> }
                    @if (file.raw_download) { <span class="block">{{ I18N.related_files.raw_download | translate }}</span> }
                  </div>
                </li>
              }
            </ul>
            @if (result.inventory_state === 'unavailable') {
              <p class="m-0">{{ I18N.related_files.unchecked | translate }}</p>
              <button type="button" class="min-h-11 cursor-pointer underline focus-visible:outline-2" (click)="load()">{{ I18N.gallery.load_error.retry | translate }}</button>
            }
            @if (result.multiple_raw_candidates) { <p class="m-0">{{ I18N.related_files.multiple_raw | translate }}</p> }
            @if (result.basename_sidecar_unverified) { <p class="m-0">{{ I18N.related_files.basename_unverified | translate }}</p> }
            <app-photo-logical-asset [photo]="photo()" (applied)="logicalApplied.emit($event)" />
            <app-context-help [label]="I18N.related_files.help_title" [keys]="helpKeys()" />
          }
        </div>
      }
    </details>
  `,
})
export class PhotoRelatedFilesComponent extends PhotoPanelReader<RelatedFilesResponse> {
  protected readonly endpoint = '/photo/related_files';
  readonly logicalApplied = output<LogicalAssetApplied>();
  protected readonly I18N = I18N;
  protected readonly helpKeys = computed(() => this.data()?.indexed_images_only
    ? [I18N.related_files.help, I18N.related_files.multi_user_scope] : [I18N.related_files.help]);
  protected readonly rows = computed(() => (this.data()?.files ?? []).map(file => ({
    ...file,
    icon: file.kind.startsWith('xmp') ? 'description' : file.kind === 'raw' ? 'raw_on' : 'image',
    kindLabel: ({ photo: I18N.related_files.photo, raw: I18N.related_files.raw, jpeg: I18N.related_files.jpeg,
      xmp_full: I18N.related_files.xmp_full, xmp_basename: I18N.related_files.xmp_basename,
      xmp_fallback: I18N.related_files.xmp_fallback })[file.kind],
    stateLabel: ({ available: I18N.related_files.available, missing: I18N.related_files.missing,
      unavailable: I18N.related_files.unavailable, link: I18N.related_files.link })[file.state],
  })));

}
