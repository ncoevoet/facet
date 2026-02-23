import { Component, input, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Photo } from '../../models/photo.model';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { StarArrayPipe, IsStarFilledPipe } from '../../pipes/star-rating.pipe';
import { ScoreClassPipe, SortScorePipe } from '../../pipes/score.pipes';

interface AppConfig {
  quality_thresholds?: { excellent: number; great: number; good: number };
  features?: {
    show_similar_button?: boolean;
    show_rating_controls?: boolean;
    show_rating_badge?: boolean;
  };
}

@Component({
  selector: 'app-photo-card',
  standalone: true,
  imports: [
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    PersonThumbnailUrlPipe,
    FixedPipe,
    ShutterSpeedPipe,
    StarArrayPipe,
    IsStarFilledPipe,
    ScoreClassPipe,
    SortScorePipe,
  ],
  template: `
    <div
      class="relative rounded-lg overflow-hidden cursor-pointer bg-neutral-900 transition-all"
      [class.md:aspect-square]="hideDetails()"
      [class.ring-2]="isSelected()"
      [class.ring-[var(--mat-sys-primary)]]="isSelected()"
      [class.hover:ring-2]="!isSelected()"
      [class.hover:ring-[var(--mat-sys-outline-variant)]]="!isSelected()"
      (click)="selectionChange.emit(photo())"
      (mouseenter)="tooltipShow.emit({photo: photo(), event: $event})"
      (mouseleave)="tooltipHide.emit()"
    >
      <!-- Image wrapper with hover overlay scoped to image only -->
      <div class="group/img relative"
           [class.md:h-full]="hideDetails()">
        <img
          [src]="photo().path | thumbnailUrl:thumbSize()"
          [alt]="photo().filename"
          loading="lazy"
          class="w-full"
          [class.md:h-full]="hideDetails()"
          [class.md:object-cover]="hideDetails()"
        />

        <!-- Persistent favorite star (visible without hover) -->
        @if (photo().is_favorite) {
          <div class="absolute top-1.5 left-1.5 z-20 pointer-events-none group-hover/img:opacity-0 transition-opacity">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-yellow-400 drop-shadow-md">star</mat-icon>
          </div>
        }

        <!-- Hover overlay (image area only) -->
        <div class="absolute inset-0 bg-black/50 opacity-0 group-hover/img:opacity-100 transition-opacity flex flex-col justify-between pointer-events-none group-hover/img:pointer-events-auto z-10">
          <!-- Top row: action buttons + star badge -->
          <div class="flex justify-end items-center gap-1 p-1.5">
            @if (photo().star_rating && config()?.features?.show_rating_badge) {
              <div class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-black/60 text-yellow-400 text-xs leading-none mr-auto">
                <mat-icon class="!text-xs !w-3 !h-3 !leading-3">star</mat-icon>
                <span class="font-medium">{{ photo().star_rating }}</span>
              </div>
            }
            @if (config()?.features?.show_similar_button) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="'similar.find_similar' | translate"
                (click)="openSimilarClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">image_search</mat-icon>
              </button>
            }
            @if (isEditionMode() && photo().unassigned_faces > 0) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="'manage_persons.assign_face' | translate"
                (click)="openAddPersonClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">person_add</mat-icon>
              </button>
            }
            @if (isEditionMode()) {
              <button
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors"
                [class.text-yellow-400]="photo().is_favorite"
                [class.text-white]="!photo().is_favorite"
                [matTooltip]="(photo().is_favorite ? 'rating.remove_favorite' : 'rating.add_favorite') | translate"
                (click)="favoriteToggled.emit(photo().path); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo().is_favorite ? 'star' : 'star_border' }}</mat-icon>
              </button>
              @if (!photo().star_rating) {
                <button
                  class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors"
                  [class.text-red-400]="photo().is_rejected"
                  [class.text-white]="!photo().is_rejected"
                  [matTooltip]="(photo().is_rejected ? 'rating.unmark_rejected' : 'rating.mark_rejected') | translate"
                  (click)="rejectedToggled.emit(photo().path); $event.stopPropagation()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo().is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
                </button>
              }
            }
          </div>

          <!-- Bottom row: star rating -->
          @if (config()?.features?.show_rating_controls && isEditionMode()) {
            <div class="flex justify-center gap-0.5 p-1.5">
              @for (star of 0 | starArray; track star) {
                <button
                  class="text-yellow-400 hover:scale-110 transition-transform"
                  (mouseenter)="starHoverChanged.emit({path: photo().path, star: star})"
                  (mouseleave)="starHoverChanged.emit({path: photo().path, star: null})"
                  (click)="starClicked.emit({photo: photo(), star: star}); $event.stopPropagation()">
                  <mat-icon class="!text-xl !w-5 !h-5">{{
                    (star | isStarFilled:photo().star_rating:hoverStar()) ? 'star' : 'star_border'
                  }}</mat-icon>
                </button>
              }
            </div>
          }
        </div>

        <!-- Selection checkmark -->
        @if (isSelected()) {
          <div class="absolute top-1.5 left-1.5 w-6 h-6 rounded-full bg-[var(--mat-sys-primary)] flex items-center justify-center z-20">
            <mat-icon class="!text-base !w-4 !h-4 text-white">check</mat-icon>
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
                <span class="px-1 py-0.5 rounded text-[10px] font-bold bg-green-700 text-white">{{ 'ui.badges.best' | translate }}</span>
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
                <span class="px-1.5 py-0.5 bg-green-900/60 text-green-400 rounded text-[11px] cursor-pointer hover:bg-green-800/60 transition-colors"
                      (click)="tagClicked.emit(tag); $event.stopPropagation()">
                  {{ tag }}
                </span>
              }
            </div>
          }
          <!-- Person avatars in details -->
          @if (photo().persons.length) {
            <div class="flex items-center gap-1 mt-0.5">
              @for (person of photo().persons; track person.id) {
                @if (isEditionMode() && personFilterId() === '' + person.id) {
                  <button
                    class="w-8 h-8 rounded-full bg-red-900/60 inline-flex items-center justify-center hover:bg-red-800 transition-colors"
                    [matTooltip]="('ui.buttons.remove' | translate) + ': ' + person.name"
                    (click)="personRemoveClicked.emit({photo: photo(), personId: person.id}); $event.stopPropagation()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4 text-red-300">close</mat-icon>
                  </button>
                } @else {
                  <img [src]="person.id | personThumbnailUrl"
                       class="w-8 h-8 rounded-full border border-neutral-700 object-cover cursor-pointer"
                       [matTooltip]="person.name"
                       (click)="personFilterClicked.emit(person.id); $event.stopPropagation()" />
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

  // Display state
  readonly isSelected = input(false);
  readonly hideDetails = input(false);
  readonly currentSort = input('aggregate');
  readonly thumbSize = input(240);

  // Edition mode
  readonly isEditionMode = input(false);
  readonly hoverStar = input<number | null>(null);
  readonly personFilterId = input('');

  // Events
  readonly selectionChange = output<Photo>();
  readonly tooltipShow = output<{ photo: Photo; event: MouseEvent }>();
  readonly tooltipHide = output<void>();
  readonly tagClicked = output<string>();
  readonly personFilterClicked = output<number>();
  readonly personRemoveClicked = output<{ photo: Photo; personId: number }>();
  readonly openSimilarClicked = output<Photo>();
  readonly openAddPersonClicked = output<Photo>();
  readonly favoriteToggled = output<string>();
  readonly rejectedToggled = output<string>();
  readonly starHoverChanged = output<{ path: string; star: number | null }>();
  readonly starClicked = output<{ photo: Photo; star: number }>();
}
