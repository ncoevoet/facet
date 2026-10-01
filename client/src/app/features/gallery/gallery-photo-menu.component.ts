import { ChangeDetectionStrategy, Component, computed, input, output, viewChild } from '@angular/core';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatMenu, MatMenuModule } from '@angular/material/menu';
import { I18N_KEYS } from '../../core/i18n/keys';
import { Album } from '../../core/services/album.service';
import { Photo } from '../../shared/models/photo.model';
import { SequenceKindIconPipe } from '../../shared/pipes/sequence-kind.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
// Type-only: the gallery imports the actions sheet with `await import(...)` on
// purpose, and a value import here would pull that chunk into the main bundle.
import type { SheetAction } from './gallery-actions-sheet.component';

/** Kinds only a single-photo menu emits; every other kind is a `SheetAction`. */
const SINGLE_ONLY_KINDS: ReadonlySet<string> = new Set([
  'open', 'similar', 'critique', 'embed', 'assign-face', 'toggle-favorite', 'toggle-reject',
]);

export type PhotoMenuAction =
  | SheetAction
  | { kind: 'open' }
  | { kind: 'similar'; mode: 'visual' | 'color' | 'person' }
  | { kind: 'critique' }
  | { kind: 'embed' }
  | { kind: 'assign-face' }
  | { kind: 'toggle-favorite' }
  | { kind: 'toggle-reject' };

export interface PhotoMenuActionEvent {
  action: PhotoMenuAction;
  photo: Photo;
  /** True when the menu was opened on a photo inside a multi-photo selection. */
  bulk: boolean;
}

export function isSheetAction(action: PhotoMenuAction): action is SheetAction {
  return !SINGLE_ONLY_KINDS.has(action.kind);
}

/** Marks the menu's own backdrop, so a right-click there is recognised as ours. */
const BACKDROP_MARKER = 'gallery-photo-menu-backdrop';

/** The slice of the viewer config the menu reads; `show_embed_metadata` is not
 *  on the store's `ViewerConfig`, as with the photo card's own config type. */
export interface PhotoMenuConfig {
  features?: {
    show_similar_button?: boolean;
    show_critique?: boolean;
    show_embed_metadata?: boolean;
    show_albums?: boolean;
  };
  cull?: { trash_available?: boolean };
}

const RATINGS = [1, 2, 3, 4, 5].map(value => ({ value, label: '★'.repeat(value) }));

/**
 * The gallery's right-click menu. One instance serves every card: the gallery
 * binds each card with `[matContextMenuTriggerFor]="menu()"` and hands the
 * photo in through `matContextMenuTriggerData` (`photo`, `bulk`, `index`).
 *
 * A bulk menu (`bulk`) offers the selection bar's actions under the bar's own
 * gates. A single menu acts on that one photo and adds the per-photo extras of
 * the card. Rate is gated on edition mode only, like the bar, not on
 * `show_rating_controls`: the menu is an explicit gesture, unlike the card's
 * always-visible star buttons.
 */
@Component({
  selector: 'app-gallery-photo-menu',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatMenuModule, MatIconModule, MatDividerModule, TranslatePipe, SequenceKindIconPipe],
  host: {
    '(document:contextmenu)': 'onDocumentContextMenu($event)',
  },
  template: `
    <mat-menu #photoMenu="matMenu" [hasBackdrop]="true" backdropClass="${BACKDROP_MARKER}" (closed)="onMenuClosed($event)">
      <ng-template matMenuContent let-photo="photo" let-bulk="bulk">
        <mat-menu #rateMenu="matMenu">
          @for (r of ratings; track r.value) {
            <button mat-menu-item (click)="emit({ kind: 'rate', rating: r.value }, photo, bulk)">{{ r.label }}</button>
          }
          <button mat-menu-item (click)="emit({ kind: 'rate', rating: 0 }, photo, bulk)">
            <span>{{ I18N.gallery.selection.clear | translate }}</span>
          </button>
        </mat-menu>
        <mat-menu #albumMenu="matMenu">
          @for (album of albums(); track album.id) {
            <button mat-menu-item (click)="emit({ kind: 'album', albumId: album.id }, photo, bulk)">
              <span>{{ album.name }}</span>
            </button>
          }
          <button mat-menu-item (click)="emit({ kind: 'create-album' }, photo, bulk)">
            <mat-icon>add</mat-icon>
            <span>{{ I18N.albums.create | translate }}</span>
          </button>
        </mat-menu>
        <mat-menu #sequenceMenu="matMenu">
          <button mat-menu-item (click)="emit({ kind: 'mark-panorama', sequenceKind: 'panorama' }, photo, bulk)">
            <mat-icon>{{ 'panorama' | sequenceKindIcon }}</mat-icon>
            <span>{{ I18N.gallery.selection.mark_panorama | translate }}</span>
          </button>
          <button mat-menu-item (click)="emit({ kind: 'mark-panorama', sequenceKind: 'hdr_panorama' }, photo, bulk)">
            <mat-icon>{{ 'hdr_panorama' | sequenceKindIcon }}</mat-icon>
            <span>{{ I18N.gallery.selection.mark_hdr_panorama | translate }}</span>
          </button>
          <button mat-menu-item (click)="emit({ kind: 'mark-panorama', sequenceKind: 'bracket' }, photo, bulk)">
            <mat-icon>{{ 'bracket' | sequenceKindIcon }}</mat-icon>
            <span>{{ I18N.gallery.selection.mark_bracket | translate }}</span>
          </button>
        </mat-menu>
        <mat-menu #similarMenu="matMenu">
          <button mat-menu-item (click)="emit({ kind: 'similar', mode: 'visual' }, photo, bulk)">
            <mat-icon>image_search</mat-icon>
            <span>{{ I18N.similar.mode_visual | translate }}</span>
          </button>
          <button mat-menu-item (click)="emit({ kind: 'similar', mode: 'color' }, photo, bulk)">
            <mat-icon>palette</mat-icon>
            <span>{{ I18N.similar.mode_color | translate }}</span>
          </button>
          <button mat-menu-item (click)="emit({ kind: 'similar', mode: 'person' }, photo, bulk)">
            <mat-icon>person_search</mat-icon>
            <span>{{ I18N.similar.mode_person | translate }}</span>
          </button>
        </mat-menu>
        <mat-menu #downloadMenu="matMenu">
          <button mat-menu-item (click)="emit({ kind: 'download', type: 'original' }, photo, bulk)">
            <mat-icon>image</mat-icon>
            <span>{{ I18N.download.type_original | translate }}</span>
          </button>
          @for (profile of downloadProfiles(); track profile) {
            <button mat-menu-item (click)="emit({ kind: 'download', type: 'darktable', profile }, photo, bulk)">
              <mat-icon>photo_filter</mat-icon>
              <span>{{ profile }}</span>
            </button>
          }
          <button mat-menu-item (click)="emit({ kind: 'download', type: 'raw' }, photo, bulk)">
            <mat-icon>raw_on</mat-icon>
            <span>{{ I18N.download.type_raw | translate }}</span>
          </button>
        </mat-menu>

        @if (!bulk) {
          <button mat-menu-item (click)="emit({ kind: 'open' }, photo, bulk)">
            <mat-icon>open_in_full</mat-icon>
            <span>{{ I18N.shortcuts.open_detail | translate }}</span>
          </button>
          @if (showSimilar()) {
            <button mat-menu-item [matMenuTriggerFor]="similarMenu">
              <mat-icon>image_search</mat-icon>
              <span>{{ I18N.similar.find_similar | translate }}</span>
            </button>
          }
          @if (showCritique()) {
            <button mat-menu-item (click)="emit({ kind: 'critique' }, photo, bulk)">
              <mat-icon>analytics</mat-icon>
              <span>{{ I18N.critique.title | translate }}</span>
            </button>
          }
          @if (isEdition() && showEmbed()) {
            <button mat-menu-item (click)="emit({ kind: 'embed' }, photo, bulk)">
              <mat-icon>save</mat-icon>
              <span>{{ I18N.photoCard.embed_to_file | translate }}</span>
            </button>
          }
          @if (isEdition() && photo.unassigned_faces > 0) {
            <button mat-menu-item (click)="emit({ kind: 'assign-face' }, photo, bulk)">
              <mat-icon>person_add</mat-icon>
              <span>{{ I18N.manage_persons.assign_face | translate }}</span>
            </button>
          }
          @if (isEdition()) {
            <mat-divider />
          }
        }

        @if (isEdition()) {
          @if (bulk) {
            <button mat-menu-item (click)="emit({ kind: 'favorite' }, photo, bulk)">
              <mat-icon>favorite</mat-icon>
              <span>{{ I18N.gallery.selection.favorite | translate }}</span>
            </button>
            <button mat-menu-item (click)="emit({ kind: 'reject' }, photo, bulk)">
              <mat-icon>thumb_down</mat-icon>
              <span>{{ I18N.gallery.selection.reject | translate }}</span>
            </button>
          } @else {
            @if (photo.is_favorite) {
              <button mat-menu-item (click)="emit({ kind: 'toggle-favorite' }, photo, bulk)">
                <mat-icon>favorite_border</mat-icon>
                <span>{{ I18N.rating.remove_favorite | translate }}</span>
              </button>
            } @else {
              <button mat-menu-item (click)="emit({ kind: 'toggle-favorite' }, photo, bulk)">
                <mat-icon>favorite</mat-icon>
                <span>{{ I18N.rating.add_favorite | translate }}</span>
              </button>
            }
            @if (photo.is_rejected) {
              <button mat-menu-item (click)="emit({ kind: 'toggle-reject' }, photo, bulk)">
                <mat-icon>thumb_down_off_alt</mat-icon>
                <span>{{ I18N.rating.unmark_rejected | translate }}</span>
              </button>
            } @else {
              <button mat-menu-item (click)="emit({ kind: 'toggle-reject' }, photo, bulk)">
                <mat-icon>thumb_down</mat-icon>
                <span>{{ I18N.rating.mark_rejected | translate }}</span>
              </button>
            }
          }
          <button mat-menu-item [matMenuTriggerFor]="rateMenu">
            <mat-icon>star</mat-icon>
            <span>{{ I18N.gallery.selection.rate | translate }}</span>
          </button>
          @if (showAlbums()) {
            <button mat-menu-item [matMenuTriggerFor]="albumMenu">
              <mat-icon>photo_library</mat-icon>
              <span>{{ I18N.albums.add_photos | translate }}</span>
            </button>
          }
          @if (bulk) {
            <button mat-menu-item [matMenuTriggerFor]="sequenceMenu">
              <mat-icon>panorama_photosphere</mat-icon>
              <span>{{ I18N.gallery.selection.mark_sequence | translate }}</span>
            </button>
            <button mat-menu-item (click)="emit({ kind: 'tags' }, photo, bulk)">
              <mat-icon>sell</mat-icon>
              <span>{{ I18N.gallery.selection.edit_tags | translate }}</span>
            </button>
          }
        }

        <button mat-menu-item (click)="emit({ kind: 'copy' }, photo, bulk)">
          <mat-icon>content_copy</mat-icon>
          <span>{{ (bulk ? I18N.gallery.selection.copy_filenames : I18N.gallery.selection.copy_filename) | translate }}</span>
        </button>

        @if (isEdition()) {
          <button mat-menu-item (click)="emit({ kind: 'export' }, photo, bulk)">
            <mat-icon>drive_file_move</mat-icon>
            <span>{{ I18N.export.action | translate }}</span>
          </button>
          <button mat-menu-item (click)="emit({ kind: 'cull' }, photo, bulk)">
            <mat-icon>folder_move</mat-icon>
            <span>{{ I18N.cull.action | translate }}</span>
          </button>
          <!-- A bulk delete is paths-only, so it is hidden rather than disabled
               under a whole-view selection; a single delete names its own path. -->
          @if (trashAvailable() && !(bulk && viewScoped())) {
            <button mat-menu-item (click)="emit({ kind: 'delete' }, photo, bulk)">
              <mat-icon>delete</mat-icon>
              <span>{{ I18N.cull.delete_action | translate }}</span>
            </button>
          }
        }

        @if (bulk && canCompare()) {
          <button mat-menu-item (click)="emit({ kind: 'compare' }, photo, bulk)">
            <mat-icon>compare</mat-icon>
            <span>{{ I18N.gallery.selection.compare | translate }}</span>
          </button>
        }

        @if (downloadProfiles().length) {
          <button mat-menu-item [matMenuTriggerFor]="downloadMenu" [disabled]="downloading()">
            <mat-icon>download</mat-icon>
            <span>{{ I18N.gallery.selection.download | translate }}</span>
          </button>
        } @else {
          <button mat-menu-item [disabled]="downloading()" (click)="emit({ kind: 'download', type: 'original' }, photo, bulk)">
            <mat-icon>download</mat-icon>
            <span>{{ I18N.gallery.selection.download | translate }}</span>
          </button>
        }
      </ng-template>
    </mat-menu>
  `,
})
export class GalleryPhotoMenuComponent {
  protected readonly I18N = I18N_KEYS;
  protected readonly ratings = RATINGS;

  readonly isEdition = input.required<boolean>();
  readonly config = input.required<PhotoMenuConfig | null>();
  readonly albums = input.required<Album[]>();
  readonly downloadProfiles = input.required<string[]>();
  readonly canCompare = input.required<boolean>();
  readonly viewScoped = input.required<boolean>();
  readonly downloading = input.required<boolean>();

  readonly action = output<PhotoMenuActionEvent>();
  /** Why the menu closed: `'click'` = an item was picked, `'keydown'` = Escape. */
  readonly closed = output<'click' | 'keydown' | 'tab' | void>();

  readonly menu = viewChild.required(MatMenu);

  protected readonly showSimilar = computed(() => !!this.config()?.features?.show_similar_button);
  protected readonly showCritique = computed(() => !!this.config()?.features?.show_critique);
  protected readonly showEmbed = computed(() => !!this.config()?.features?.show_embed_metadata);
  protected readonly showAlbums = computed(() => !!this.config()?.features?.show_albums);
  protected readonly trashAvailable = computed(() => !!this.config()?.cull?.trash_available);

  /** The picked item, held until the menu reports `closed`. Material runs the
   *  item's click before that event, so emitting at once would open a dialog
   *  while focus still sits on the menu item about to be destroyed, and the
   *  dialog would restore focus to <body>. */
  private pending: PhotoMenuActionEvent | null = null;

  protected emit(action: PhotoMenuAction, photo: Photo, bulk: boolean): void {
    this.pending = { action, photo, bulk };
  }

  /** Hands the owner its `closed` first (it refocuses the card), then the
   *  picked action, so a dialog it opens captures the card as its
   *  focus-restore target. */
  protected onMenuClosed(reason: 'click' | 'keydown' | 'tab' | void): void {
    this.closed.emit(reason);
    const picked = this.pending;
    this.pending = null;
    if (picked) this.action.emit(picked);
  }

  /** While the menu is open its backdrop covers the page, so a right-click
   *  lands there and would raise the browser's native menu over the photos.
   *  Swallow it and close instead. */
  protected onDocumentContextMenu(event: MouseEvent): void {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.classList.contains(BACKDROP_MARKER)) return;
    event.preventDefault();
    this.menu().closed.emit();
  }
}
