import { ChangeDetectionStrategy, Component, effect, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import type { PhotoAlbum } from '../../core/api/types';
import { I18N } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PhotoPanelReader } from './photo-panel-reader';

/** The albums containing a photo, read as soon as the photo shows (no panel to open); renders nothing when there are none. */
@Component({
  selector: 'app-photo-albums',
  imports: [RouterLink, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block min-w-0' },
  template: `
    @if (data(); as albums) {
      @if (albums.length) {
        <section data-photo-albums aria-labelledby="photo-albums-title">
          <h2 id="photo-albums-title" class="m-0 mb-1 text-xs font-normal text-[var(--mat-sys-on-surface-variant)]">{{ I18N.nav.albums | translate }}</h2>
          <ul class="m-0 flex list-none flex-wrap gap-1.5 p-0">
            @for (album of albums; track album.id) {
              <li class="min-w-0 max-w-full">
                <a [routerLink]="['/album', album.id]" data-album-chip
                   [attr.aria-label]="album.is_smart ? (I18N.photo_detail.labelled_value | translate:{ label: (I18N.albums.smart_album | translate), value: album.name }) : null"
                   class="inline-flex min-h-8 max-w-full items-center gap-1 rounded-full border border-[var(--mat-sys-outline-variant)] px-3 text-xs no-underline hover:bg-[var(--mat-sys-surface-container)] focus-visible:outline-2 [@media(pointer:coarse)]:min-h-11">
                  @if (album.is_smart) {
                    <mat-icon aria-hidden="true" class="!h-4 !w-4 shrink-0 !text-base">auto_awesome</mat-icon>
                  }
                  <bdi class="truncate">{{ album.name }}</bdi>
                </a>
              </li>
            }
          </ul>
        </section>
      }
    }
  `,
})
export class PhotoAlbumsComponent extends PhotoPanelReader<PhotoAlbum[]> {
  protected readonly endpoint = '/photo/albums';
  protected readonly I18N = I18N;

  constructor() {
    super();
    // The base resets on every path or session change (and while a navigation is pending); read again once it settles.
    effect(() => {
      const settled = !this.navigating && !!this.auth.session() && !!this.photo().path;
      untracked(() => { if (settled && !this.expanded()) this.setExpanded(true); });
    });
  }
}
