import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MAT_BOTTOM_SHEET_DATA, MatBottomSheetRef } from '@angular/material/bottom-sheet';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SequenceKindIconPipe } from '../../shared/pipes/sequence-kind.pipe';
import { Album } from '../../core/services/album.service';
import { i18nKeys } from '../../core/i18n/keys';
import { refreshBlockedReason } from './gallery-selection-actions';

export type SheetAction =
  | { kind: 'refresh' }
  | { kind: 'stack' }
  | { kind: 'favorite' }
  | { kind: 'reject' }
  | { kind: 'review'; decision: 'kept' | 'undecided' }
  | { kind: 'select-all' }
  | { kind: 'invert' }
  | { kind: 'compare' }
  | { kind: 'export' }
  | { kind: 'cull' }
  | { kind: 'tags' }
  | { kind: 'capture-date' }
  | { kind: 'gps' }
  | { kind: 'remove-catalog' }
  | { kind: 'delete' }
  | { kind: 'rate'; rating: number }
  | { kind: 'mark-panorama'; sequenceKind: 'panorama' | 'hdr_panorama' | 'bracket' }
  | { kind: 'album'; albumId: number }
  | { kind: 'create-album' }
  | { kind: 'copy' }
  | { kind: 'download'; type: string; profile?: string };

export interface GalleryActionsSheetData {
  count: number;
  isEdition: boolean;
  showAlbums: boolean;
  albums: Album[];
  downloadProfiles: string[];
  /** Whether the selection size is within the compare surface's pane bounds. */
  canCompare: boolean;
  canStack?: boolean;
  /** False once every loaded photo is selected, as the desktop Actions menu hides Select all then. */
  canSelectAll?: boolean;
  viewScoped?: boolean;
  /** Gates the delete entry -- `_cull_capabilities.trash_available`, never the
   *  raw `allow_trash` flag (a button gated on that alone would 400 on an
   *  install where the flag is on but `send2trash` isn't installed). */
  trashAvailable: boolean;
}

/** Touch-friendly bulk-actions sheet replacing the cramped mobile action bar. It lists the desktop
 *  Actions menu in the same order, each submenu as a labelled section, so the two read alike. */
@Component({
  selector: 'app-gallery-actions-sheet',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, MatIconModule, TranslatePipe, SequenceKindIconPipe],
  template: `
    <div class="flex flex-col pb-2">
      <div class="flex items-center justify-between gap-2 pl-4 pr-1 py-1 text-sm font-medium border-b border-[var(--mat-sys-outline-variant)]">
        {{ I18N.gallery.selection.count | translate:{ count: data.count } }}
        <button mat-icon-button data-sheet-close (click)="close()" [attr.aria-label]="I18N.dialog.close | translate">
          <mat-icon aria-hidden="true">close</mat-icon>
        </button>
      </div>

      @if (data.viewScoped) { <p class="px-4 py-2 text-sm">{{ I18N.stacks.folded_scope | translate }}</p> }
      @if (data.canCompare) {
        <button [class]="row" (click)="pick({ kind: 'compare' })"><mat-icon aria-hidden="true">compare</mat-icon>{{ I18N.gallery.selection.compare | translate }}</button>
      }
      @if (data.canSelectAll) {
        <button [class]="row" (click)="pick({ kind: 'select-all' })"><mat-icon aria-hidden="true">select_all</mat-icon>{{ I18N.gallery.selection.select_all | translate }}</button>
      }
      <button [class]="row" (click)="pick({ kind: 'invert' })"><mat-icon aria-hidden="true">flip</mat-icon>{{ I18N.gallery.selection.invert | translate }}</button>

      @if (data.isEdition) {
        <div role="group" aria-labelledby="actions-sheet-review" [class]="section">
          <h2 id="actions-sheet-review" [class]="heading">{{ I18N.gallery.sidebar.tabs.review | translate }}</h2>
          <button [class]="row" (click)="pick({ kind: 'review', decision: 'kept' })"><mat-icon aria-hidden="true">check_circle</mat-icon>{{ I18N.review.keep | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'reject' })"><mat-icon aria-hidden="true">thumb_down</mat-icon>{{ I18N.gallery.selection.reject | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'favorite' })"><mat-icon aria-hidden="true">favorite</mat-icon>{{ I18N.gallery.selection.favorite | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'review', decision: 'undecided' })"><mat-icon aria-hidden="true">restart_alt</mat-icon>{{ I18N.review.reset | translate }}</button>
          <div class="flex flex-wrap items-center gap-1 px-4 py-1">
            @for (star of ratings; track star) {
              <button class="min-h-11 min-w-11 rounded-full text-yellow-400 text-sm font-semibold hover:bg-white/10 cursor-pointer"
                      [attr.aria-label]="(I18N.gallery.selection.rate | translate) + ' ' + star"
                      (click)="pick({ kind: 'rate', rating: star })">{{ star }}★</button>
            }
            <button class="min-h-11 rounded-full px-3 text-sm hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'rate', rating: 0 })">{{ I18N.gallery.selection.clear_rating | translate }}</button>
          </div>
        </div>
        @if (data.showAlbums) {
          <div role="group" aria-labelledby="actions-sheet-albums" [class]="section">
            <h2 id="actions-sheet-albums" [class]="heading">{{ I18N.albums.add_photos | translate }}</h2>
            @for (album of data.albums; track album.id) {
              <button [class]="row" (click)="pick({ kind: 'album', albumId: album.id })"><mat-icon aria-hidden="true">photo_library</mat-icon>{{ album.name }}</button>
            }
            <button [class]="row" (click)="pick({ kind: 'create-album' })"><mat-icon aria-hidden="true">add</mat-icon>{{ I18N.albums.create | translate }}</button>
          </div>
        }
        <div role="group" aria-labelledby="actions-sheet-sets" [class]="section">
          <h2 id="actions-sheet-sets" [class]="heading">{{ I18N.gallery.selection.mark_sequence | translate }}</h2>
          <button [class]="row" (click)="pick({ kind: 'mark-panorama', sequenceKind: 'panorama' })"><mat-icon aria-hidden="true">{{ 'panorama' | sequenceKindIcon }}</mat-icon>{{ I18N.gallery.selection.mark_panorama | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'mark-panorama', sequenceKind: 'hdr_panorama' })"><mat-icon aria-hidden="true">{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>{{ I18N.gallery.selection.mark_hdr_panorama | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'mark-panorama', sequenceKind: 'bracket' })"><mat-icon aria-hidden="true">{{ 'bracket' | sequenceKindIcon }}</mat-icon>{{ I18N.gallery.selection.mark_bracket | translate }}</button>
        </div>
        <div role="group" aria-labelledby="actions-sheet-metadata" [class]="section">
          <h2 id="actions-sheet-metadata" [class]="heading">{{ I18N.gallery.selection.edit_metadata | translate }}</h2>
          <button [class]="row" (click)="pick({ kind: 'capture-date' })"><mat-icon aria-hidden="true">edit_calendar</mat-icon>{{ I18N.capture_date.title | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'gps' })"><mat-icon aria-hidden="true">location_on</mat-icon>{{ I18N.photo_detail.gps.batch_title | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'tags' })"><mat-icon aria-hidden="true">sell</mat-icon>{{ I18N.gallery.selection.edit_tags | translate }}</button>
        </div>
      }
      @if (data.downloadProfiles.length) {
        <div role="group" aria-labelledby="actions-sheet-download" [class]="section">
          <h2 id="actions-sheet-download" [class]="heading">{{ I18N.gallery.selection.download | translate }}</h2>
          <button [class]="row" (click)="pick({ kind: 'download', type: 'original' })"><mat-icon aria-hidden="true">image</mat-icon>{{ I18N.download.type_original | translate }}</button>
          @for (profile of data.downloadProfiles; track profile) {
            <button [class]="row" (click)="pick({ kind: 'download', type: 'darktable', profile })"><mat-icon aria-hidden="true">photo_filter</mat-icon>{{ profile }}</button>
          }
          <button [class]="row" (click)="pick({ kind: 'download', type: 'raw' })"><mat-icon aria-hidden="true">raw_on</mat-icon>{{ I18N.download.type_raw | translate }}</button>
        </div>
      } @else {
        <!-- Ruled off on its own, or it reads as one more Edit metadata entry. -->
        <div [class]="section">
          <button [class]="row" (click)="pick({ kind: 'download', type: 'original' })"><mat-icon aria-hidden="true">download</mat-icon>{{ I18N.gallery.selection.download | translate }}</button>
        </div>
      }

      <div [class]="section">
        @if (data.isEdition) {
          <button [class]="row" [disabled]="!data.canStack" [attr.aria-describedby]="data.canStack ? null : 'actions-sheet-stack-reason'" (click)="pick({ kind: 'stack' })"><mat-icon aria-hidden="true">photo_library</mat-icon>{{ I18N.stacks.create | translate }}</button>
          @if (!data.canStack) { <p id="actions-sheet-stack-reason" [class]="reason">{{ I18N.stacks.explicit_only | translate }}</p> }
        }
        <button [class]="row" (click)="pick({ kind: 'copy' })"><mat-icon aria-hidden="true">content_copy</mat-icon>{{ I18N.gallery.selection.copy_filenames | translate }}</button>
        @if (data.isEdition) {
          <button [class]="row" (click)="pick({ kind: 'export' })"><mat-icon aria-hidden="true">drive_file_move</mat-icon>{{ I18N.export.action | translate }}</button>
          <button [class]="row" (click)="pick({ kind: 'cull' })"><mat-icon aria-hidden="true">move_to_inbox</mat-icon>{{ I18N.cull.action | translate }}</button>
          <button [class]="row" [disabled]="!!refreshBlocked" [attr.aria-describedby]="refreshBlocked ? 'actions-sheet-refresh-reason' : null" (click)="pick({ kind: 'refresh' })"><mat-icon aria-hidden="true">refresh</mat-icon>{{ I18N.photo_refresh.title | translate }}</button>
          @if (refreshBlocked) { <p id="actions-sheet-refresh-reason" [class]="reason">{{ refreshBlocked | translate }}</p> }
        }
      </div>

      @if (data.isEdition) {
        <div [class]="section">
          <button [class]="row" [disabled]="data.viewScoped" [attr.aria-describedby]="data.viewScoped ? 'actions-sheet-remove-reason' : null" (click)="pick({ kind: 'remove-catalog' })"><mat-icon aria-hidden="true">hide_image</mat-icon>{{ I18N.photo_detail.remove_catalog.action | translate }}</button>
          @if (data.viewScoped) { <p id="actions-sheet-remove-reason" [class]="reason">{{ I18N.gallery.selection.explicit_required | translate }}</p> }
          @if (data.trashAvailable) {
            <button [class]="row" [disabled]="data.viewScoped" [attr.aria-describedby]="data.viewScoped ? 'actions-sheet-delete-reason' : null" (click)="pick({ kind: 'delete' })"><mat-icon aria-hidden="true">delete</mat-icon>{{ I18N.cull.delete_action | translate }}</button>
            @if (data.viewScoped) { <p id="actions-sheet-delete-reason" [class]="reason">{{ I18N.cull.delete_disabled_view_scope_tooltip | translate }}</p> }
          }
        </div>
      }
    </div>
  `,
  host: { class: 'block' },
})
export class GalleryActionsSheetComponent {
  protected readonly I18N = i18nKeys();
  protected readonly data = inject<GalleryActionsSheetData>(MAT_BOTTOM_SHEET_DATA);
  protected readonly ratings = [1, 2, 3, 4, 5];
  protected readonly refreshBlocked = refreshBlockedReason(!!this.data.viewScoped, this.data.count);
  protected readonly row = 'flex min-h-11 w-full cursor-pointer items-center gap-3 px-4 py-2 text-left text-sm hover:bg-white/10 disabled:cursor-default disabled:opacity-40';
  protected readonly section = 'mt-1 border-t border-[var(--mat-sys-outline-variant)] pt-1';
  protected readonly heading = 'm-0 px-4 pt-2 pb-1 text-xs font-medium text-[var(--mat-sys-on-surface-variant)]';
  protected readonly reason = 'm-0 px-4 pb-2 pl-13 text-xs text-[var(--mat-sys-on-surface-variant)]';
  private readonly sheetRef = inject(MatBottomSheetRef<GalleryActionsSheetComponent>);

  protected pick(action: SheetAction): void {
    this.sheetRef.dismiss(action);
  }

  protected close(): void {
    this.sheetRef.dismiss();
  }
}
