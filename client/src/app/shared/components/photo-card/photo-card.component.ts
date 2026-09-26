import { Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { Photo } from '../../models/photo.model';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { SequenceOverrideBadgeKeyPipe } from '../../pipes/sequence-kind.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindBestLabelPipe } from '../../pipes/photo-set-kind.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { ScoreClassPipe, SortScorePipe } from '../../pipes/score.pipes';
import { SortPersonsPipe } from '../../pipes/sort-persons.pipe';

interface AppConfig {
  quality_thresholds?: { excellent: number; great: number; good: number };
  features?: {
    show_similar_button?: boolean;
    show_rating_controls?: boolean;
    show_critique?: boolean;
    show_embed_metadata?: boolean;
  };
  badges?: Partial<BadgeVisibility>;
  clipping?: { badge_percent?: number };
}

/** Which card badges are drawn, from `viewer.badges`. */
export interface BadgeVisibility {
  favorite: boolean;
  star_rating: boolean;
  rejected: boolean;
  sequence_kind: boolean;
  sequence_override_pending: boolean;
  keeper_hint: boolean;
  best_of_burst: boolean;
  clipping_highlight: boolean;
  clipping_shadow: boolean;
}

/** Every badge that predates the config block stays on, so an install that
 *  says nothing about badges looks exactly as it did. Shadow clipping is the
 *  one default-off badge: crushed blacks are routinely deliberate. */
export const DEFAULT_BADGE_VISIBILITY: BadgeVisibility = {
  favorite: true,
  star_rating: true,
  rejected: true,
  sequence_kind: true,
  sequence_override_pending: true,
  keeper_hint: true,
  best_of_burst: true,
  clipping_highlight: true,
  clipping_shadow: false,
};

const DEFAULT_CLIPPING_BADGE_PERCENT = 5;

@Component({
  selector: 'app-photo-card',
  standalone: true,
  host: {
    role: 'gridcell',
    style: 'content-visibility: auto; contain-intrinsic-size: auto 300px',
    // Room for the scrollIntoView the grid's keyboard cursor performs on the
    // card it lands on. That call asks for `block: 'nearest'`, which is the
    // least scrolling that brings an edge of the card to an edge of the
    // scrollport and which takes no account of anything drawn over it -- and
    // the gallery fixes an action bar across the bottom of the viewport for as
    // long as anything is selected, which is exactly when the arrow keys are in
    // use. Arrowing downward therefore parked the current card underneath it,
    // star-rating badge and all, that badge sitting in the bottom-left corner.
    // The clearance is sized for the tallest case the bar actually reaches.
    // From lg up the scrollport runs to the bottom of the viewport, so the bar
    // is what the card has to clear, and its height is not one number: given
    // enough width the controls sit on a single row of 61px -- 1px of border,
    // 36px of button at this theme's -1 density, and 12px of py-3 above and
    // below it -- but from lg to around 1300px they wrap to a second row and it
    // measures 93px. Adding the 6px the marker's own outline occupies outside
    // the card puts the requirement at 99px, which is why this is 7rem: 5rem
    // left 19px of the outline under the bar at those widths, and 6rem still
    // falls 3px short. Below lg the shell already holds the scrollport 56px
    // clear of the viewport bottom for its own nav, so the same 7rem merely
    // over-scrolls a little, which shows more of the next row and costs
    // nothing. One value rather than a binding on
    // whether the bar is up: scroll-margin is inert until something calls
    // scrollIntoView, and the only caller runs synchronously inside the keydown
    // handler, ahead of the change detection that would have to apply a
    // conditional class. The top asks for nothing but that same outline kept
    // off the scrollport's edge, since nothing in the shell is fixed or sticky
    // above the grid.
    class: 'scroll-mt-2 scroll-mb-28 reduce-transparency:opacity-100',
    // The current-photo marker, and the dimming of every card that is not it.
    // Both sit on the host rather than on the tile below, because the host's
    // own `content-visibility: auto` brings paint containment with it, and that
    // clips whatever a descendant draws outside the card's box -- the tile's
    // focus-visible outline included. The host's own outline is the one that
    // still reaches the 8px gutter, and the gutter is the only place a frame is
    // not competing with the photograph for contrast: a line on the tile's edge
    // loses to skin tones and blurred background, which is what the 2px
    // selection ring already demonstrates. offset-2 plus 4px lands it entirely
    // on the page background, 2px clear of the next card.
    '[class.outline-4]': 'isActive()',
    '[class.outline-[var(--mat-sys-tertiary)]]': 'isActive()',
    '[class.outline-offset-2]': 'isActive()',
    // Matches the tile's own rounding so the offset outline is concentric with
    // it rather than cutting square corners past it.
    '[class.rounded-lg]': 'isActive()',
    // The hosts are flex/grid items, so this applies without positioning them.
    // Well under the action bar (z-50) and the scroll-to-top button (z-40).
    '[class.z-10]': 'isActive()',
    // Users who set "reduce transparency" get the outline and aria-current
    // above without this large-area translucency: the static
    // reduce-transparency:opacity-100 class cancels it back to full opacity.
    '[class.opacity-50]': 'isDimmed()',
  },
  imports: [
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    SequenceOverrideBadgeKeyPipe,
    PhotoSetKindIconPipe,
    PhotoSetKindBestLabelPipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
    ShutterSpeedPipe,
    ScoreClassPipe,
    SortScorePipe,
    SortPersonsPipe,
  ],
  template: `
    <div
      role="button"
      tabindex="0"
      class="relative rounded-lg overflow-hidden cursor-pointer bg-[var(--mat-sys-surface-container)] transition-all h-full focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)] focus-visible:outline-offset-2"
      [class.md:aspect-square]="hideDetails() && !mosaicMode()"
      [class.ring-2]="isSelected()"
      [class.ring-[var(--mat-sys-primary)]]="isSelected()"
      [class.md:hover:ring-2]="!isSelected()"
      [class.md:hover:ring-[var(--mat-sys-outline-variant)]]="!isSelected()"
      [attr.aria-label]="photo().keeper_hint?.has_better ? photo().filename + ', ' + ('culling.reason.better_shot' | translate) : photo().filename"
      [attr.aria-pressed]="isSelected()"
      [attr.aria-current]="isActive() ? 'true' : null"
      (click)="onSelect($event)"
      (keydown.enter)="onKeyOpen($event)"
      (keydown.space)="onKeySelect($event)"
      (dblclick)="doubleClicked.emit(photo()); $event.stopPropagation()"
      (mouseenter)="onMouseEnter($event)"
      (mouseleave)="onMouseLeave()"
    >
      <!-- Image wrapper with hover overlay scoped to image only -->
      <div class="group/img relative"
           [class.md:h-full]="hideDetails()">
        <img
          [src]="photo().path | thumbnailUrl:thumbSize()"
          [alt]="photo().caption || photo().filename"
          loading="lazy"
          decoding="async"
          class="w-full bg-[var(--mat-sys-surface-container)] transition-opacity duration-500"
          [class.md:h-full]="hideDetails()"
          [class.md:object-cover]="hideDetails()"
          [class.grayscale]="isEditionMode() && photo().is_rejected"
          [class.opacity-60]="isEditionMode() && photo().is_rejected"
          [style.opacity]="imageLoaded() ? (isEditionMode() && photo().is_rejected ? '0.6' : '1') : '0'"
          (load)="imageLoaded.set(true)"
        />

        <!-- Persistent badges.
             Each one occupies the EXACT box of the hover-bar control it stands
             for -- same w-7 h-7, same bottom-1, same left-1.5 / right-1.5 /
             right-9 the bar's own px-1.5 py-1 and gap-0.5 produce. They were
             6px off before, which read as the icons jumping every time the
             pointer entered or left the tile. -->
        @if (showsFavoriteBadge()) {
          <div class="absolute bottom-1 right-1.5 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-red-400 drop-shadow-md">favorite</mat-icon>
          </div>
        }

        <!-- A rating the user set is a standing fact about the photo, so it
             should not take a hover to see it. Carries the same count bubble the
             control does. -->
        @if (badges().star_rating && isEditionMode() && photo().star_rating) {
          <div class="absolute bottom-1 left-1.5 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0"
               [attr.aria-label]="'rating.rating_badge' | translate:{ stars: photo().star_rating ?? 0 }">
            <mat-icon class="!text-lg !w-[18px] !h-[18px] !leading-[18px] !text-yellow-400 drop-shadow-md"
                      aria-hidden="true">star</mat-icon>
            <span class="absolute -top-0.5 -right-0.5 min-w-3.5 h-3.5 rounded-full bg-yellow-500 text-black text-[10px] font-bold flex items-center justify-center leading-none">{{ photo().star_rating }}</span>
          </div>
        }

        <!-- This tile stands for a whole set, not one photo. With a hide
             toggle on, the other frames are collapsed behind it and nothing
             else on the tile would say so. Shown only while the matching hide
             toggle collapses this photo's set: with it off every frame is on
             screen in its own right, and badging all of them says nothing. It
             does NOT fade under the hover bar the way the rating badges do --
             those fade because the bar replaces them with their own controls,
             whereas this one states a fact the bar never repeats, so hiding it
             on hover just loses information. Sits above the bar's gradient.
             Position is packed against whichever of favorite/rejected is
             showing (setKindBadgePosition()): flush right when neither is up,
             next-slot-in when one is, and clear of both when rejected is up --
             and in edition mode it also steps clear on hover, since that is
             when the bar's own heart/reject buttons occupy those slots. -->
        @if (badges().sequence_kind && collapsedSetKind(); as kind) {
          <div [class]="'absolute bottom-1 w-7 h-7 z-30 inline-flex items-center justify-center ' + setKindBadgePosition()"
               [matTooltip]="kind | photoSetKindBestLabel | translate"
               [attr.aria-label]="kind | photoSetKindBestLabel | translate">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-white drop-shadow-md"
                      aria-hidden="true">{{ kind | photoSetKindIcon }}</mat-icon>
          </div>
        }

        <!-- A pending panorama correction. Keyed on the override, never on
             sequence_kind: a set the detector never grouped has no kind at all
             until the next run, and that miss is exactly what was corrected.
             Unconditional, unlike the badge above -- a correction is not
             collapsed behind anything, so a hide toggle says nothing about it. -->
        @if (badges().sequence_override_pending && photo().sequence_override_pending && photo().sequence_override; as pending) {
          <div class="absolute bottom-1 left-[4.5rem] w-7 h-7 z-30 inline-flex items-center justify-center"
               [matTooltip]="(pending | sequenceOverrideBadgeKey) | translate"
               [attr.aria-label]="(pending | sequenceOverrideBadgeKey) | translate">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-amber-300 drop-shadow-md"
                      aria-hidden="true">schedule</mat-icon>
          </div>
        }

        <!-- Persistent rejected badge (shape + desaturation, not color alone).
             Sits where the hover bar's own reject button sits, right of the
             heart. It does NOT yield to a star rating: the two occupy opposite
             corners so they never collided, and hiding it left desaturation as
             the only signal -- which conveys nothing to a screen reader and
             nothing at all on an already-monochrome photo. -->
        @if (showsRejectedBadge()) {
          <div class="absolute bottom-1 right-9 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0"
               [attr.aria-label]="'rating.rejected_badge' | translate">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-red-400 drop-shadow-md" aria-hidden="true">thumb_down</mat-icon>
          </div>
        }

        <!-- Keeper hint: a better shot exists in this group (learned keeper head) -->
        @if (badges().keeper_hint && photo().keeper_hint?.has_better) {
          <div class="absolute top-1.5 left-3 z-20 pointer-events-none flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 transition-opacity md:group-hover/img:opacity-0">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-amber-300 drop-shadow-md" aria-hidden="true">arrow_circle_up</mat-icon>
          </div>
        }

        <!-- Clipping: a channel ran out of range and lost its detail. Top
             right, fading on hover so it never sits under the overlay's own
             buttons. Highlight and shadow are separate badges because they are
             separate decisions -- a blown sky is usually a mistake, crushed
             blacks are routinely the point -- which is why shadow is off by
             default. A photo whose row was never measured has no percentage at
             all and is silent, rather than claiming to be clean. -->
        @if (clipping(); as clip) {
          <div class="absolute top-1.5 right-1.5 z-20 pointer-events-none flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 transition-opacity md:group-hover/img:opacity-0"
               [attr.aria-label]="clip.label | translate:{ percent: clip.percentText }">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 drop-shadow-md"
                      [class]="clip.colorClass" aria-hidden="true">{{ clip.icon }}</mat-icon>
          </div>
        }

        <!-- Hover overlay (image area only, md+ only, disabled when tooltip hidden) -->
        <div class="absolute inset-0 opacity-0 transition-opacity flex flex-col justify-between pointer-events-none z-10 md:group-hover/img:opacity-100 md:group-hover/img:pointer-events-auto">
          <!-- Top row: similar + person_add -->
          <div class="flex justify-end items-center gap-1 p-1.5">
            @if (config()?.features?.show_similar_button) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white cursor-pointer"
                [matMenuTriggerFor]="similarMenu"
                [matTooltip]="'similar.find_similar' | translate"
                [attr.aria-label]="'similar.find_similar' | translate"
                (click)="$event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">image_search</mat-icon>
              </button>
              <mat-menu #similarMenu="matMenu">
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'visual'})">
                  <mat-icon>image_search</mat-icon>
                  {{ 'similar.mode_visual' | translate }}
                </button>
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'color'})">
                  <mat-icon>palette</mat-icon>
                  {{ 'similar.mode_color' | translate }}
                </button>
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'person'})">
                  <mat-icon>person_search</mat-icon>
                  {{ 'similar.mode_person' | translate }}
                </button>
              </mat-menu>
            }
            @if (config()?.features?.show_critique) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white cursor-pointer"
                [matTooltip]="'critique.title' | translate"
                [attr.aria-label]="'critique.title' | translate"
                (click)="openCritiqueClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">analytics</mat-icon>
              </button>
            }
            @if (isEditionMode() && config()?.features?.show_embed_metadata) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white cursor-pointer"
                [matTooltip]="'photoCard.embed_to_file' | translate"
                [attr.aria-label]="'photoCard.embed_to_file' | translate"
                (click)="embedMetadataClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">save</mat-icon>
              </button>
            }
            @if (isEditionMode() && photo().unassigned_faces > 0) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white cursor-pointer"
                [matTooltip]="'manage_persons.assign_face' | translate"
                [attr.aria-label]="'manage_persons.assign_face' | translate"
                (click)="openAddPersonClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">person_add</mat-icon>
              </button>
            }
          </div>

          <!-- Bottom bar: star rating (left) + favorite/reject (right) -->
          @if (isEditionMode()) {
            <div class="flex items-center justify-between px-1.5 py-1 bg-gradient-to-t from-black/70 to-transparent">
              <!-- Left: compact star rating -->
              @if (config()?.features?.show_rating_controls) {
                <button
                  class="relative w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors text-yellow-400 cursor-pointer"
                  [matTooltip]="'rating.set_rating' | translate"
                  [attr.aria-label]="'rating.set_rating' | translate"
                  (click)="cycleStarRating(); $event.stopPropagation()"
                  (dblclick)="$event.stopPropagation()">
                  <mat-icon class="!text-lg !w-[18px] !h-[18px] !leading-[18px]">{{ photo().star_rating ? 'star' : 'star_border' }}</mat-icon>
                  @if (photo().star_rating) {
                    <span class="absolute -top-0.5 -right-0.5 min-w-3.5 h-3.5 rounded-full bg-yellow-500 text-black text-[10px] font-bold flex items-center justify-center leading-none">{{ photo().star_rating }}</span>
                  }
                </button>
              }
              <!-- Right: reject + favorite -->
              <div class="flex items-center gap-0.5 ml-auto">
                @if (!photo().star_rating) {
                  <button
                    class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors cursor-pointer"
                    [class.text-red-400]="photo().is_rejected"
                    [class.text-white]="!photo().is_rejected"
                    [matTooltip]="(photo().is_rejected ? 'rating.unmark_rejected' : 'rating.mark_rejected') | translate"
                    [attr.aria-label]="(photo().is_rejected ? 'rating.unmark_rejected' : 'rating.mark_rejected') | translate"
                    [attr.aria-pressed]="!!photo().is_rejected"
                    (click)="rejectedToggled.emit(photo().path); $event.stopPropagation()"
                    (dblclick)="$event.stopPropagation()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">{{ photo().is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
                  </button>
                }
                <button
                  class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors cursor-pointer"
                  [class.text-red-400]="photo().is_favorite"
                  [class.text-white]="!photo().is_favorite"
                  [matTooltip]="(photo().is_favorite ? 'rating.remove_favorite' : 'rating.add_favorite') | translate"
                  [attr.aria-label]="(photo().is_favorite ? 'rating.remove_favorite' : 'rating.add_favorite') | translate"
                  [attr.aria-pressed]="!!photo().is_favorite"
                  (click)="favoriteToggled.emit(photo().path); $event.stopPropagation()"
                  (dblclick)="$event.stopPropagation()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">{{ photo().is_favorite ? 'favorite' : 'favorite_border' }}</mat-icon>
                </button>
              </div>
            </div>
          }
        </div>

        <!-- Selection checkmark -->
        @if (isSelected()) {
          <div class="absolute top-1.5 left-1.5 w-6 h-6 rounded-full bg-[var(--mat-sys-primary)] flex items-center justify-center z-20" aria-hidden="true">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-white">check</mat-icon>
          </div>
        }
      </div>

      <!-- Details below photo -->
      @if (!hideDetails()) {
        <div class="pt-1 text-xs text-neutral-300 leading-snug">
          <div class="flex items-center gap-1">
            <span class="font-medium text-neutral-200 truncate">{{ photo().filename }}</span>
            <span class="ml-auto flex items-center gap-1 shrink-0">
              @if (showsBestBadge()) {
                <span class="px-1 py-0.5 rounded text-[10px] font-bold bg-[var(--facet-accent-dim)] text-white">{{ 'ui.badges.best' | translate }}</span>
              }
              @if (currentSort() !== 'aggregate') {
                <span class="text-neutral-400 font-medium" [matTooltip]="'gallery.aggregate_score' | translate">{{ photo().aggregate | fixed:1 }}</span>
              }
              <span
                class="px-1 py-0.5 rounded text-xs font-bold"
                [class]="(photo() | sortScore:currentSort()) | scoreClass:config()"
                [matTooltip]="(currentSort() === 'aggregate' ? ('gallery.aggregate_score' | translate) : ('gallery.sort_score' | translate) + ' (' + currentSort() + ')')"
              >{{ (photo() | sortScore:currentSort()) | fixed:1 }}</span>
            </span>
          </div>
          @if (photo().date_taken) {
            <div class="text-neutral-500">{{ photo().date_taken }}</div>
          }
          <div class="text-neutral-500">
            @if (photo().focal_length) { {{ photo().focal_length }}mm }
            @if (photo().f_stop) { f/{{ photo().f_stop }} }
            @if (photo().shutter_speed) { {{ photo().shutter_speed | shutterSpeed }} }
            @if (photo().iso) { ISO {{ photo().iso }} }
          </div>
          @if (photo().tags_list.length) {
            <div class="flex gap-0.5 flex-wrap mt-0.5">
              @for (tag of photo().tags_list; track tag) {
                <span class="px-1.5 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded text-[11px] cursor-pointer hover:bg-[var(--facet-accent-dim)] transition-colors"
                      role="button"
                      tabindex="0"
                      (click)="tagClicked.emit(tag); $event.stopPropagation()"
                      (keydown.enter)="tagClicked.emit(tag); $event.stopPropagation()"
                      (keydown.space)="tagClicked.emit(tag); $event.preventDefault(); $event.stopPropagation()">
                  {{ tag }}
                </span>
              }
            </div>
          }
          <!-- Person avatars in details -->
          @if (photo().persons.length) {
            <div class="flex items-center gap-1 mt-0.5">
              @for (person of photo().persons | sortPersons:personFilterId(); track person.id) {
                @if (isEditionMode() && personFilterId() === '' + person.id) {
                  <button
                    class="w-8 h-8 rounded-full bg-red-900/60 inline-flex items-center justify-center hover:bg-red-800 transition-colors cursor-pointer"
                    [matTooltip]="('ui.buttons.remove' | translate) + ': ' + person.name"
                    [attr.aria-label]="('ui.buttons.remove' | translate) + ': ' + person.name"
                    (click)="personRemoveClicked.emit({photo: photo(), personId: person.id}); $event.stopPropagation()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-red-300">close</mat-icon>
                  </button>
                } @else {
                  <img [src]="person.id | personThumbnailUrl"
                       class="w-8 h-8 rounded-full border border-neutral-700 object-cover cursor-pointer"
                       [alt]="person.name"
                       [matTooltip]="person.name"
                       role="button"
                       tabindex="0"
                       (click)="personFilterClicked.emit(person.id); $event.stopPropagation()"
                       (keydown.enter)="personFilterClicked.emit(person.id); $event.stopPropagation()"
                       (keydown.space)="personFilterClicked.emit(person.id); $event.preventDefault(); $event.stopPropagation()" />
                }
              }
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class PhotoCardComponent {
  // Data
  readonly photo = input.required<Photo>();
  readonly config = input<AppConfig | null>(null);

  /** Which badges this install draws, with every unset key left at its default. */
  protected readonly badges = computed<BadgeVisibility>(
    () => ({ ...DEFAULT_BADGE_VISIBILITY, ...(this.config()?.badges ?? {}) }));

  /** Single source of truth for the favorite badge's @if -- also drives
   *  setKindBadgePosition() so the set-kind badge packs against it rather
   *  than the two conditions drifting apart. */
  protected readonly showsFavoriteBadge = computed(() =>
    this.badges().favorite && this.isEditionMode() && !!this.photo().is_favorite);

  /** Single source of truth for the rejected badge's @if -- see
   *  showsFavoriteBadge(). */
  protected readonly showsRejectedBadge = computed(() =>
    this.badges().rejected && this.isEditionMode() && !!this.photo().is_rejected);

  /**
   * Tailwind position classes for the set-kind "Best of ..." badge, packed
   * against whichever of favorite/rejected is showing so it never overlaps
   * them: flush right (favorite's own slot) when neither is up, the
   * rejected slot when only favorite is up, and clear of both -- the
   * pre-existing right-[4.125rem] -- whenever rejected is up (with or
   * without favorite). In edition mode the hover bar redraws its own
   * heart/reject buttons in those same slots, so this also steps clear on
   * hover; outside edition mode there is no bar to clear, so no hover class.
   */
  protected readonly setKindBadgePosition = computed(() => {
    const hoverClear = this.isEditionMode() ? ' md:group-hover/img:right-[4.125rem]' : '';
    if (this.showsRejectedBadge()) return 'right-[4.125rem]' + hoverClear;
    if (this.showsFavoriteBadge()) return 'right-9' + hoverClear;
    return 'right-1.5' + hoverClear;
  });

  /**
   * The clipping badge for this photo, or null when it has not earned one.
   *
   * Highlights win when both directions clip: a blown highlight is
   * unrecoverable, while a crushed black usually still reads as black.
   * A null percentage means the photo was never measured (its stored
   * histogram predates the per-channel format) and is treated as unknown,
   * never as clean.
   */
  protected readonly clipping = computed(() => {
    const badges = this.badges();
    const threshold = this.config()?.clipping?.badge_percent ?? DEFAULT_CLIPPING_BADGE_PERCENT;
    const highlight = this.photo().channel_clip_highlight_pct;
    const shadow = this.photo().channel_clip_shadow_pct;
    if (badges.clipping_highlight && highlight != null && highlight > threshold) {
      return {
        label: 'gallery.clipping.badge_highlight',
        icon: 'flare',
        colorClass: '!text-amber-300',
        percentText: highlight.toFixed(1),
      };
    }
    if (badges.clipping_shadow && shadow != null && shadow > threshold) {
      return {
        label: 'gallery.clipping.badge_shadow',
        icon: 'brightness_low',
        colorClass: '!text-sky-300',
        percentText: shadow.toFixed(1),
      };
    }
    return null;
  });

  /**
   * Whether this card carries the "Best" badge.
   *
   * `burst_group_id` is an INTEGER counting from 0, so the library's first
   * burst group has the id `0` and a truthiness test silently drops it. Only
   * null/undefined means "in no burst", which is why this is a null check.
   */
  protected readonly showsBestBadge = computed(() =>
    this.badges().best_of_burst
    && this.burstFramesVisible()
    && !!this.photo().is_burst_lead
    && this.photo().burst_group_id != null);

  /**
   * The set kind to badge for this tile, or null when nothing is collapsed
   * behind it.
   *
   * `sequence_kind` (bracket/panorama/hdr_panorama) wins when present -- it is
   * the deliberate, detector-assigned kind. Burst and duplicate have no
   * `sequence_kind` counterpart, so they fall back to the same lead+group-id
   * check `showsBestBadge` uses; `burst_group_id`/`duplicate_group_id` count
   * from 0, so only a null group id means "not in this kind of set".
   */
  protected readonly collapsedSetKind = computed<string | null>(() => {
    const collapsed = this.collapsedSetKinds();
    const photo = this.photo();
    if (photo.sequence_kind && collapsed.includes(photo.sequence_kind)) {
      return photo.sequence_kind;
    }
    if (collapsed.includes('burst') && !!photo.is_burst_lead && photo.burst_group_id != null) {
      return 'burst';
    }
    if (collapsed.includes('duplicate') && !!photo.is_duplicate_lead && photo.duplicate_group_id != null) {
      return 'duplicate';
    }
    return null;
  });

  // Progressive loading
  readonly imageLoaded = signal(false);
  private previousPath = '';

  constructor() {
    effect(() => {
      const path = this.photo().path;
      if (path !== untracked(() => this.previousPath)) {
        untracked(() => {
          this.previousPath = path;
          this.imageLoaded.set(false);
        });
      }
    });
  }

  // Display state
  readonly isSelected = input(false);
  /** Whether this card is the one the grid's keyboard cursor is standing on.
   *
   *  Independent of `isSelected`: a card can be both, and the two say different
   *  things -- selection is a set the batch actions operate on, current is the
   *  single photo the next rating keystroke lands on. */
  readonly isActive = input(false);
  /** Whether the grid this card sits in has a current photo at all.
   *
   *  Stated as a fact about the grid rather than passed as "dim yourself": a
   *  card cannot see whether some *other* card is the current one. It stays
   *  false until the grid's cursor first lands somewhere, which is what keeps
   *  a gallery nobody has navigated yet from rendering every tile faded. */
  readonly gridHasActiveCard = input(false);
  readonly hideDetails = input(false);
  readonly mosaicMode = input(false);
  readonly currentSort = input('aggregate');
  readonly thumbSize = input(240);

  /** Every card except the current one, and only once there is a current one.
   *
   *  Fading the rest is the half of the marker that a photograph cannot defeat:
   *  a line drawn at the tile's own edge competes with whatever the photo puts
   *  there, whereas a grid where one tile alone is at full strength reads from
   *  across the room. */
  protected readonly isDimmed = computed(() => this.gridHasActiveCard() && !this.isActive());

  // Edition mode
  readonly isEditionMode = input(false);
  /** Set kinds currently collapsed behind a representative frame.
   *
   *  Passed in rather than read from the gallery's filter state, so this shared
   *  component keeps knowing nothing about a feature store. Empty means no hide
   *  toggle is on, and the badge would then be claiming a set is collapsed when
   *  every one of its frames is on screen. */
  readonly collapsedSetKinds = input<readonly string[]>([]);
  /** Whether a burst's non-lead frames are on screen.
   *
   *  The mirror image of `collapsedSetKinds`: with `hide_bursts` on --
   *  the default -- every burst photo in the grid IS its group's lead, so a
   *  "best" badge on each would be decoration. It only carries information
   *  once the siblings it was picked over are visible beside it. */
  readonly burstFramesVisible = input(false);
  readonly personFilterId = input('');
  /** 'hover' (default) | 'click' | 'off' | 'panel' — drives tooltip emission strategy.
   *
   *  'panel' feeds the gallery's docked rail. By default it responds to BOTH
   *  gestures: it was asked for as "changes with the photo selected (click) or
   *  hovered (hover)", and since the rail is parked rather than chasing the
   *  cursor there is no reason to make that an either/or by default. It also
   *  keeps the rail usable on a touch screen, where hover never fires.
   *  panelActivation narrows this per-install/per-user. */
  readonly tooltipMode = input<'hover' | 'click' | 'off' | 'panel'>('hover');
  /** Which gesture(s) retarget the docked panel when tooltipMode is 'panel'.
   *  Irrelevant for every other mode, which already has one fixed gesture.
   *  Default 'both' preserves the original panel behaviour exactly. */
  readonly panelActivation = input<'hover' | 'click' | 'both'>('both');

  /** Whether a mouse hover retargets the panel: always for 'hover', for
   *  'panel' only when panelActivation allows hover. */
  private hoverDriven(): boolean {
    const mode = this.tooltipMode();
    if (mode === 'hover') return true;
    if (mode === 'panel') return this.panelActivation() !== 'click';
    return false;
  }

  /** Whether a mouse click retargets the panel: always for 'click', for
   *  'panel' only when panelActivation allows click. */
  private clickDriven(): boolean {
    const mode = this.tooltipMode();
    if (mode === 'click') return true;
    if (mode === 'panel') return this.panelActivation() !== 'hover';
    return false;
  }

  /** Keyboard selection always retargets 'click' and 'panel', regardless of
   *  panelActivation -- a keyboard user has no hover to fall back on, so
   *  narrowing this the same way as clickDriven() would strand them. */
  private keyboardDriven(): boolean {
    const mode = this.tooltipMode();
    return mode === 'click' || mode === 'panel';
  }

  // Events
  readonly selectionChange = output<{ photo: Photo; event: MouseEvent }>();

  onSelect(event: MouseEvent): void {
    this.selectionChange.emit({ photo: this.photo(), event });
    if (this.clickDriven()) {
      this.tooltipShow.emit({ photo: this.photo(), event });
    }
  }

  /** Space is the keyboard's click, so it feeds the details panel the same way. */
  onKeySelect(event: Event): void {
    event.preventDefault();
    this.selectionChange.emit({ photo: this.photo(), event: event as MouseEvent });
    if (this.keyboardDriven()) {
      this.tooltipShow.emit({ photo: this.photo(), event: event as MouseEvent });
    }
  }

  onKeyOpen(event: Event): void {
    event.preventDefault();
    this.doubleClicked.emit(this.photo());
  }

  onMouseEnter(event: MouseEvent): void {
    if (this.hoverDriven()) {
      this.tooltipShow.emit({ photo: this.photo(), event });
    }
  }

  onMouseLeave(): void {
    if (this.hoverDriven()) {
      this.tooltipHide.emit();
    }
  }
  readonly tooltipShow = output<{ photo: Photo; event: MouseEvent }>();
  readonly tooltipHide = output<void>();
  readonly tagClicked = output<string>();
  readonly personFilterClicked = output<number>();
  readonly personRemoveClicked = output<{ photo: Photo; personId: number }>();
  readonly openSimilarClicked = output<{ photo: Photo; mode: 'visual' | 'color' | 'person' }>();
  readonly openCritiqueClicked = output<Photo>();
  readonly embedMetadataClicked = output<Photo>();
  readonly openAddPersonClicked = output<Photo>();
  readonly favoriteToggled = output<string>();
  readonly rejectedToggled = output<string>();
  readonly starClicked = output<{ photo: Photo; star: number }>();
  readonly doubleClicked = output<Photo>();

  cycleStarRating(): void {
    const current = this.photo().star_rating ?? 0;
    this.starClicked.emit({ photo: this.photo(), star: current >= 5 ? 0 : current + 1 });
  }
}
