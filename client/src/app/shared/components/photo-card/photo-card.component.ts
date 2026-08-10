import { Component, effect, input, output, signal, untracked } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { Photo } from '../../models/photo.model';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { SequenceKindIconPipe, SequenceKindLabelPipe } from '../../pipes/sequence-kind.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { ScoreClassPipe, SortScorePipe } from '../../pipes/score.pipes';
import { SortPersonsPipe } from '../../pipes/sort-persons.pipe';
import { I18N } from '../../../core/i18n/keys';

interface AppConfig {
  quality_thresholds?: { excellent: number; great: number; good: number };
  features?: {
    show_similar_button?: boolean;
    show_rating_controls?: boolean;
    show_rating_badge?: boolean;
    show_critique?: boolean;
    show_embed_metadata?: boolean;
  };
}

@Component({
  selector: 'app-photo-card',
  standalone: true,
  host: { role: 'gridcell', style: 'content-visibility: auto; contain-intrinsic-size: auto 300px' },
  imports: [
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatMenuModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    SequenceKindIconPipe,
    SequenceKindLabelPipe,
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
      [attr.aria-label]="photo().keeper_hint?.has_better ? photo().filename + ', ' + (I18N.culling.reason.better_shot | translate) : photo().filename"
      [attr.aria-pressed]="isSelected()"
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
        @if (isEditionMode() && photo().is_favorite) {
          <div class="absolute bottom-1 right-1.5 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-red-400 drop-shadow-md">favorite</mat-icon>
          </div>
        }

        <!-- A rating the user set is a standing fact about the photo, so it
             should not take a hover to see it. Carries the same count bubble the
             control does. -->
        @if (isEditionMode() && photo().star_rating) {
          <div class="absolute bottom-1 left-1.5 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0"
               [attr.aria-label]="I18N.rating.rating_badge | translate:{ stars: photo().star_rating ?? 0 }">
            <mat-icon class="!text-lg !w-[18px] !h-[18px] !leading-[18px] !text-yellow-400 drop-shadow-md"
                      aria-hidden="true">star</mat-icon>
            <span class="absolute -top-0.5 -right-0.5 min-w-3.5 h-3.5 rounded-full bg-yellow-500 text-black text-[10px] font-bold flex items-center justify-center leading-none">{{ photo().star_rating }}</span>
          </div>
        }

        <!-- This tile stands for a whole set, not one photo. With the hide
             toggle on, the other frames are collapsed behind it and nothing
             else on the tile would say so. Bottom row, just past the star's
             slot: every persistent badge keeps a fixed position so they never
             trade places as a photo is favourited or rated. Shown only while the
             matching hide toggle is on: with it off every frame is on screen in
             its own right, and badging all of them says nothing. It does NOT fade
             under the hover bar the way the rating badges do -- those fade
             because the bar replaces them with their own controls, whereas this
             one states a fact the bar never repeats, so hiding it on hover just
             loses information. Sits above the bar's gradient. -->
        @if (collapsedSequenceKinds().includes(photo().sequence_kind ?? '')) {
          <div class="absolute bottom-1 left-10 w-7 h-7 z-30 inline-flex items-center justify-center"
               [matTooltip]="photo().sequence_kind | sequenceKindLabel | translate"
               [attr.aria-label]="photo().sequence_kind | sequenceKindLabel | translate">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-sky-300 drop-shadow-md"
                      aria-hidden="true">{{ photo().sequence_kind | sequenceKindIcon }}</mat-icon>
          </div>
        }

        <!-- Persistent rejected badge (shape + desaturation, not color alone).
             Sits where the hover bar's own reject button sits, right of the
             heart. It does NOT yield to a star rating: the two occupy opposite
             corners so they never collided, and hiding it left desaturation as
             the only signal -- which conveys nothing to a screen reader and
             nothing at all on an already-monochrome photo. -->
        @if (isEditionMode() && photo().is_rejected) {
          <div class="absolute bottom-1 right-9 w-7 h-7 z-20 pointer-events-none inline-flex items-center justify-center transition-opacity md:group-hover/img:opacity-0"
               [attr.aria-label]="I18N.rating.rejected_badge | translate">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-red-400 drop-shadow-md" aria-hidden="true">thumb_down</mat-icon>
          </div>
        }

        <!-- Keeper hint: a better shot exists in this group (learned keeper head) -->
        @if (photo().keeper_hint?.has_better) {
          <div class="absolute top-1.5 left-3 z-20 pointer-events-none flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 transition-opacity md:group-hover/img:opacity-0">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-amber-300 drop-shadow-md" aria-hidden="true">arrow_circle_up</mat-icon>
          </div>
        }

        <!-- Hover overlay (image area only, md+ only, disabled when tooltip hidden) -->
        <div class="absolute inset-0 opacity-0 transition-opacity flex flex-col justify-between pointer-events-none z-10 md:group-hover/img:opacity-100 md:group-hover/img:pointer-events-auto">
          <!-- Top row: similar + person_add -->
          <div class="flex justify-end items-center gap-1 p-1.5">
            @if (config()?.features?.show_similar_button) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matMenuTriggerFor]="similarMenu"
                [matTooltip]="I18N.similar.find_similar | translate"
                (click)="$event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">image_search</mat-icon>
              </button>
              <mat-menu #similarMenu="matMenu">
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'visual'})">
                  <mat-icon>image_search</mat-icon>
                  {{ I18N.similar.mode_visual | translate }}
                </button>
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'color'})">
                  <mat-icon>palette</mat-icon>
                  {{ I18N.similar.mode_color | translate }}
                </button>
                <button mat-menu-item (click)="openSimilarClicked.emit({photo: photo(), mode: 'person'})">
                  <mat-icon>person_search</mat-icon>
                  {{ I18N.similar.mode_person | translate }}
                </button>
              </mat-menu>
            }
            @if (config()?.features?.show_critique) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="I18N.critique.title | translate"
                (click)="openCritiqueClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">analytics</mat-icon>
              </button>
            }
            @if (isEditionMode() && config()?.features?.show_embed_metadata) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="I18N.photoCard.embed_to_file | translate"
                [attr.aria-label]="I18N.photoCard.embed_to_file | translate"
                (click)="embedMetadataClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">save</mat-icon>
              </button>
            }
            @if (isEditionMode() && photo().unassigned_faces > 0) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="I18N.manage_persons.assign_face | translate"
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
                  class="relative w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors text-yellow-400"
                  [matTooltip]="I18N.rating.set_rating | translate"
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
                    class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors"
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
                  class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors"
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
              @if (photo().is_best_of_burst) {
                <span class="px-1 py-0.5 rounded text-[10px] font-bold bg-[var(--facet-accent-dim)] text-white">{{ I18N.ui.badges.best | translate }}</span>
              }
              @if (currentSort() !== 'aggregate') {
                <span class="text-neutral-400 font-medium" [matTooltip]="I18N.gallery.aggregate_score | translate">{{ photo().aggregate | fixed:1 }}</span>
              }
              <span
                class="px-1 py-0.5 rounded text-xs font-bold"
                [class]="(photo() | sortScore:currentSort()) | scoreClass:config()"
                [matTooltip]="(currentSort() === 'aggregate' ? (I18N.gallery.aggregate_score | translate) : (I18N.gallery.sort_score | translate) + ' (' + currentSort() + ')')"
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
                    class="w-8 h-8 rounded-full bg-red-900/60 inline-flex items-center justify-center hover:bg-red-800 transition-colors"
                    [matTooltip]="(I18N.ui.buttons.remove | translate) + ': ' + person.name"
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
  protected readonly I18N = I18N;
  // Data
  readonly photo = input.required<Photo>();
  readonly config = input<AppConfig | null>(null);

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
  readonly hideDetails = input(false);
  readonly mosaicMode = input(false);
  readonly currentSort = input('aggregate');
  readonly thumbSize = input(240);

  // Edition mode
  readonly isEditionMode = input(false);
  /** Sequence kinds currently collapsed behind a representative frame.
   *
   *  Passed in rather than read from the gallery's filter state, so this shared
   *  component keeps knowing nothing about a feature store. Empty means no hide
   *  toggle is on, and the badge would then be claiming a set is collapsed when
   *  every one of its frames is on screen. */
  readonly collapsedSequenceKinds = input<readonly string[]>([]);
  readonly personFilterId = input('');
  /** 'hover' (default) | 'click' | 'off' | 'panel' — drives tooltip emission strategy.
   *
   *  'panel' feeds the gallery's docked rail, which is the one mode driven by
   *  BOTH gestures: it was asked for as "changes with the photo selected (click)
   *  or hovered (hover)", and since the rail is parked rather than chasing the
   *  cursor there is no reason to make that an either/or. It also keeps the rail
   *  usable on a touch screen, where hover never fires. */
  readonly tooltipMode = input<'hover' | 'click' | 'off' | 'panel'>('hover');

  /** Whether this mode reports hover at all (both hover and the docked rail do). */
  private hoverDriven(): boolean {
    return this.tooltipMode() === 'hover' || this.tooltipMode() === 'panel';
  }

  /** Whether this mode reports clicks (the click tooltip and the docked rail). */
  private clickDriven(): boolean {
    return this.tooltipMode() === 'click' || this.tooltipMode() === 'panel';
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
    if (this.clickDriven()) {
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
