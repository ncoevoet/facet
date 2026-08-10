import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Photo } from '../../shared/models/photo.model';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SyncedZoomComponent, ZoomState, FIT_ZOOM, MAX_COMPARE_PANES } from './synced-zoom.component';
import { I18N } from '../../core/i18n/keys';

export interface CompareSelectedData {
  photos: Photo[];
}

/**
 * Side-by-side pixel-peeking over a hand-picked gallery selection.
 *
 * The culling lightbox already compares frames this way, but only ever the ones
 * sitting next to each other in a burst. Deciding between two shots of the same
 * subject taken minutes apart -- or from different folders entirely -- had no
 * surface at all. This reuses `SyncedZoomComponent` wholesale, including its
 * swap to a full-resolution source past the fit scale, so both places pan and
 * zoom identically rather than growing two implementations of the same gesture.
 */
@Component({
  selector: 'app-compare-selected-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatDialogModule, MatIconModule, MatButtonModule, MatTooltipModule,
    SyncedZoomComponent, ThumbnailUrlPipe, ImageUrlPipe, TranslatePipe,
  ],
  template: `
    <div class="flex flex-col h-full bg-black">
      <div class="flex items-center gap-2 px-3 py-2 text-white/90 text-sm shrink-0">
        <mat-icon class="!text-base !w-5 !h-5 !leading-5">compare</mat-icon>
        <span class="flex-1 truncate">{{ I18N.gallery.compare.title | translate:{ count: panes().length } }}</span>
        @if (zoomed()) {
          <button mat-icon-button class="!text-white"
                  [matTooltip]="I18N.gallery.compare.reset_zoom | translate"
                  [attr.aria-label]="I18N.gallery.compare.reset_zoom | translate"
                  (click)="resetZoom()">
            <mat-icon>zoom_out_map</mat-icon>
          </button>
        }
        <button mat-icon-button class="!text-white"
                [matTooltip]="I18N.dialog.close | translate"
                [attr.aria-label]="I18N.dialog.close | translate"
                (click)="close()">
          <mat-icon>close</mat-icon>
        </button>
      </div>

      <div class="flex-1 min-h-0 grid grid-cols-2 gap-1 p-1"
           [class.!grid-cols-1]="panes().length < 2"
           [class.grid-rows-2]="panes().length > 2">
        @for (photo of panes(); track photo.path) {
          <div class="relative w-full h-full min-h-0 rounded overflow-hidden">
            <app-synced-zoom class="w-full h-full min-h-0"
                             [src]="photo.path | thumbnailUrl:1920"
                             [fullResSrc]="photo.path | imageUrl:true"
                             [zoom]="zoom()"
                             (zoomChange)="zoom.set($event)"
                             [alt]="photo.filename" />
            <div class="absolute bottom-1 left-1 right-1 px-2 py-0.5 rounded bg-black/60 text-white text-xs truncate">
              {{ photo.filename }}
            </div>
          </div>
        }
      </div>

      <div class="px-3 py-2 text-center text-white/60 text-xs shrink-0">
        {{ I18N.gallery.compare.hint | translate }}
      </div>
    </div>
  `,
  host: { class: 'block h-full' },
})
export class CompareSelectedDialogComponent {
  protected readonly I18N = I18N;
  private readonly dialogRef = inject(MatDialogRef<CompareSelectedDialogComponent>);
  private readonly data = inject<CompareSelectedData>(MAT_DIALOG_DATA);

  /** Pan/zoom shared by every pane, so a gesture on one moves them all in lockstep. */
  protected readonly zoom = signal<ZoomState>({ ...FIT_ZOOM });

  /** Extra selected photos are dropped rather than shrunk past usefulness. */
  protected readonly panes = computed(() => (this.data.photos ?? []).slice(0, MAX_COMPARE_PANES));

  protected readonly zoomed = computed(() => this.zoom().scale > FIT_ZOOM.scale);

  protected resetZoom(): void {
    this.zoom.set({ ...FIT_ZOOM });
  }

  protected close(): void {
    this.dialogRef.close();
  }
}
