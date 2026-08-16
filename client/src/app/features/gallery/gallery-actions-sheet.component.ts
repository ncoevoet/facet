import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MAT_BOTTOM_SHEET_DATA, MatBottomSheetRef } from '@angular/material/bottom-sheet';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SequenceKindIconPipe } from '../../shared/pipes/sequence-kind.pipe';
import { Album } from '../../core/services/album.service';
import { I18N_KEYS } from '../../core/i18n/keys';

export type SheetAction =
  | { kind: 'favorite' }
  | { kind: 'reject' }
  | { kind: 'invert' }
  | { kind: 'compare' }
  | { kind: 'export' }
  | { kind: 'cull' }
  | { kind: 'rate'; rating: number }
  | { kind: 'mark-panorama'; sequenceKind: 'panorama' | 'hdr_panorama' }
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
}

/** Touch-friendly bulk-actions sheet replacing the cramped mobile action bar. */
@Component({
  selector: 'app-gallery-actions-sheet',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatIconModule, TranslatePipe, SequenceKindIconPipe],
  template: `
    <div class="flex flex-col pb-2">
      <div class="px-4 py-3 text-sm font-medium border-b border-[var(--mat-sys-outline-variant)]">
        {{ I18N.gallery.selection.count | translate:{ count: data.count } }}
      </div>

      @if (data.isEdition) {
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'favorite' })">
          <mat-icon aria-hidden="true">favorite</mat-icon>
          {{ I18N.gallery.selection.favorite | translate }}
        </button>
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'reject' })">
          <mat-icon aria-hidden="true">thumb_down</mat-icon>
          {{ I18N.gallery.selection.reject | translate }}
        </button>
        <div class="flex items-center gap-1 px-4 py-2">
          <mat-icon class="mr-2 opacity-70" aria-hidden="true">star</mat-icon>
          @for (star of [1, 2, 3, 4, 5]; track star) {
            <button
              class="w-9 h-9 rounded-full text-yellow-400 text-sm font-semibold hover:bg-white/10 cursor-pointer"
              [attr.aria-label]="(I18N.gallery.selection.rate | translate) + ' ' + star"
              (click)="pick({ kind: 'rate', rating: star })"
            >{{ star }}★</button>
          }
          <button class="w-9 h-9 rounded-full text-sm hover:bg-white/10 cursor-pointer"
                  [attr.aria-label]="I18N.gallery.selection.clear | translate"
                  (click)="pick({ kind: 'rate', rating: 0 })">0</button>
        </div>
        @if (data.showAlbums) {
          @for (album of data.albums; track album.id) {
            <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'album', albumId: album.id })">
              <mat-icon aria-hidden="true">photo_library</mat-icon>
              {{ album.name }}
            </button>
          }
          <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'create-album' })">
            <mat-icon aria-hidden="true">add</mat-icon>
            {{ I18N.albums.create | translate }}
          </button>
        }
        <!-- Present on the desktop bar but previously unreachable on a phone,
             where this sheet is the only way to any bulk action. -->
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'export' })">
          <mat-icon aria-hidden="true">drive_file_move</mat-icon>
          {{ I18N.export.action | translate }}
        </button>
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'cull' })">
          <mat-icon aria-hidden="true">folder_move</mat-icon>
          {{ I18N.cull.action | translate }}
        </button>
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'mark-panorama', sequenceKind: 'panorama' })">
          <mat-icon aria-hidden="true">{{ 'panorama' | sequenceKindIcon }}</mat-icon>
          {{ I18N.gallery.selection.mark_panorama | translate }}
        </button>
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'mark-panorama', sequenceKind: 'hdr_panorama' })">
          <mat-icon aria-hidden="true">{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>
          {{ I18N.gallery.selection.mark_hdr_panorama | translate }}
        </button>
      }

      <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'invert' })">
        <mat-icon aria-hidden="true">flip</mat-icon>
        {{ I18N.gallery.selection.invert | translate }}
      </button>
      @if (data.canCompare) {
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'compare' })">
          <mat-icon aria-hidden="true">compare</mat-icon>
          {{ I18N.gallery.selection.compare | translate }}
        </button>
      }
      <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'copy' })">
        <mat-icon aria-hidden="true">content_copy</mat-icon>
        {{ I18N.gallery.selection.copy_filenames | translate }}
      </button>
      <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'download', type: 'original' })">
        <mat-icon aria-hidden="true">download</mat-icon>
        {{ I18N.download.type_original | translate }}
      </button>
      @for (profile of data.downloadProfiles; track profile) {
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'download', type: 'darktable', profile })">
          <mat-icon aria-hidden="true">photo_filter</mat-icon>
          {{ profile }}
        </button>
      }
      @if (data.downloadProfiles.length) {
        <button class="flex items-center gap-3 w-full px-4 py-3 text-sm text-left hover:bg-white/10 cursor-pointer" (click)="pick({ kind: 'download', type: 'raw' })">
          <mat-icon aria-hidden="true">raw_on</mat-icon>
          {{ I18N.download.type_raw | translate }}
        </button>
      }
    </div>
  `,
  host: { class: 'block' },
})
export class GalleryActionsSheetComponent {
  protected readonly I18N = I18N_KEYS;
  protected readonly data = inject<GalleryActionsSheetData>(MAT_BOTTOM_SHEET_DATA);
  private readonly sheetRef = inject(MatBottomSheetRef<GalleryActionsSheetComponent>);

  protected pick(action: SheetAction): void {
    this.sheetRef.dismiss(action);
  }
}
