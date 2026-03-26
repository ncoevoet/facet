import { Component, effect, input, output, signal, untracked } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatMenuModule } from '@angular/material/menu';
import { Photo } from '../../models/photo.model';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { ScoreClassPipe, SortScorePipe } from '../../pipes/score.pipes';
import { SortPersonsPipe } from '../../pipes/sort-persons.pipe';

interface AppConfig {
  quality_thresholds?: { excellent: number; great: number; good: number };
  features?: {
    show_similar_button?: boolean;
    show_rating_controls?: boolean;
    show_rating_badge?: boolean;
    show_critique?: boolean;
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
    PersonThumbnailUrlPipe,
    FixedPipe,
    ShutterSpeedPipe,
    ScoreClassPipe,
    SortScorePipe,
    SortPersonsPipe,
  ],
  template: `
    <div
      class="relative rounded-lg overflow-hidden cursor-pointer bg-[var(--mat-sys-surface-container)] transition-all h-full"
      [class.md:aspect-square]="hideDetails() && !mosaicMode()"
      [class.ring-2]="isSelected()"
      [class.ring-[var(--mat-sys-primary)]]="isSelected()"
      [class.md:hover:ring-2]="!isSelected()"
      [class.md:hover:ring-[var(--mat-sys-outline-variant)]]="!isSelected()"
      (click)="onSelect($event)"
      (dblclick)="doubleClicked.emit(photo()); $event.stopPropagation()"
      (mouseenter)="tooltipShow.emit({photo: photo(), event: $event})"
      (mouseleave)="tooltipHide.emit()"
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
          [style.opacity]="imageLoaded() ? '1' : '0'"
          (load)="imageLoaded.set(true)"
        />

        <!-- Persistent favorite heart (visible without hover, bottom-right, edition mode only) -->
        @if (isEditionMode() && photo().is_favorite) {
          <div class="absolute bottom-1.5 right-3 z-20 pointer-events-none transition-opacity md:group-hover/img:opacity-0">
            <mat-icon class="!text-base !w-4 !h-4 !leading-4 !text-red-400 drop-shadow-md">favorite</mat-icon>
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
                [matTooltip]="'similar.find_similar' | translate"
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
                class="w-7 h-7 rounded-full bg-black/50 inline-flex items-center justify-center hover:bg-black/80 transition-colors text-white"
                [matTooltip]="'critique.title' | translate"
                (click)="openCritiqueClicked.emit(photo()); $event.stopPropagation()">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">analytics</mat-icon>
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
          </div>

          <!-- Bottom bar: star rating (left) + favorite/reject (right) -->
          @if (isEditionMode()) {
            <div class="flex items-center justify-between px-1.5 py-1 bg-gradient-to-t from-black/70 to-transparent">
              <!-- Left: compact star rating -->
              @if (config()?.features?.show_rating_controls) {
                <button
                  class="relative w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors text-yellow-400"
                  [matTooltip]="'rating.set_rating' | translate"
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
                    (click)="rejectedToggled.emit(photo().path); $event.stopPropagation()"
                    (dblclick)="$event.stopPropagation()">
                    <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo().is_rejected ? 'thumb_down' : 'thumb_down_off_alt' }}</mat-icon>
                  </button>
                }
                <button
                  class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors"
                  [class.text-red-400]="photo().is_favorite"
                  [class.text-white]="!photo().is_favorite"
                  [matTooltip]="(photo().is_favorite ? 'rating.remove_favorite' : 'rating.add_favorite') | translate"
                  (click)="favoriteToggled.emit(photo().path); $event.stopPropagation()"
                  (dblclick)="$event.stopPropagation()">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">{{ photo().is_favorite ? 'favorite' : 'favorite_border' }}</mat-icon>
                </button>
              </div>
            </div>
          }
        </div>

        <!-- Selection checkmark -->
        @if (isSelected()) {
          <div class="absolute top-1.5 left-1.5 w-6 h-6 rounded-full bg-[var(--mat-sys-primary)] flex items-center justify-center z-20">
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
                      (click)="tagClicked.emit(tag); $event.stopPropagation()">
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
  readonly personFilterId = input('');

  // Events
  readonly selectionChange = output<{ photo: Photo; event: MouseEvent }>();

  onSelect(event: MouseEvent): void {
    this.selectionChange.emit({ photo: this.photo(), event });
  }
  readonly tooltipShow = output<{ photo: Photo; event: MouseEvent }>();
  readonly tooltipHide = output<void>();
  readonly tagClicked = output<string>();
  readonly personFilterClicked = output<number>();
  readonly personRemoveClicked = output<{ photo: Photo; personId: number }>();
  readonly openSimilarClicked = output<{ photo: Photo; mode: 'visual' | 'color' | 'person' }>();
  readonly openCritiqueClicked = output<Photo>();
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
