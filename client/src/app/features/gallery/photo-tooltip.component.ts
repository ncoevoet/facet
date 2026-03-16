import { Component, Pipe, PipeTransform, computed, input } from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { Photo } from '../../shared/models/photo.model';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../shared/pipes/shutter-speed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

/** Replace underscores with spaces for display (e.g. "rule_of_thirds" → "Rule Of Thirds"). */
@Pipe({ name: 'categoryLabel', standalone: true, pure: true })
export class CategoryLabelPipe implements PipeTransform {
  private titleCase = new TitleCasePipe();
  transform(value: string | null): string {
    if (!value) return '';
    return this.titleCase.transform(value.replace(/_/g, ' '));
  }
}

@Component({
  selector: 'app-photo-tooltip',
  imports: [FixedPipe, ShutterSpeedPipe, TranslatePipe, ThumbnailUrlPipe, CategoryLabelPipe],
  template: `
    @if (photo(); as p) {
      <div
        class="fixed z-[1000] pointer-events-none flex flex-col backdrop-blur-sm p-2.5 rounded-xl shadow-2xl"
        style="background: var(--facet-tooltip-bg); border: 1px solid var(--facet-tooltip-border)"
        [style.left.px]="x()"
        [style.top.px]="y()"
      >
        <!-- Zone A: Image + Scoring sections -->
        <div class="flex items-start gap-3"
          [class.flex-col]="isLandscape()"
          [class.flex-row-reverse]="!isLandscape() && flipped()"
        >
          <!-- Image preview -->
          <img
            [src]="p.path | thumbnailUrl:640"
            [alt]="p.filename"
            class="rounded-md object-contain shrink-0"
            [class.max-h-[40vh]]="!isLandscape()"
            [class.w-full]="isLandscape()"
            [class.max-h-[28vh]]="isLandscape()"
          />

          <!-- Scoring panel -->
          <div class="text-xs leading-relaxed text-[var(--facet-tooltip-text)]"
            [class.min-w-[240px]]="!isLandscape()"
            [class.max-w-[260px]]="!isLandscape()"
            [class.w-full]="isLandscape()"
          >
            <!-- Filename + Date -->
            <div class="font-semibold text-[var(--facet-tooltip-text-title)] truncate"
              [class.flex]="isLandscape()"
              [class.justify-between]="isLandscape()"
              [class.items-baseline]="isLandscape()"
              [class.gap-3]="isLandscape()"
            >
              <span class="truncate">{{ p.filename }}</span>
              @if (p.date_taken) {
                <span class="text-[var(--facet-tooltip-text-muted)] text-[11px] font-normal shrink-0"
                  [class.block]="!isLandscape()"
                >{{ p.date_taken }}</span>
              }
            </div>

            <!-- Category + aggregate + star rating -->
            <div class="flex items-baseline justify-between mb-1.5">
              <span class="text-[var(--mat-sys-primary)] font-semibold">[{{ p.category | categoryLabel }}] {{ 'tooltip.aggregate' | translate }}: {{ p.aggregate | fixed:1 }}</span>
              @if (p.star_rating) {
                <span class="text-yellow-400 font-semibold shrink-0 ml-2">★{{ p.star_rating }}</span>
              }
            </div>

            <!-- Caption (after score) -->
            @if (p.caption_translated || p.caption) {
              <div class="text-xs italic text-[var(--facet-tooltip-text-muted)] mb-1.5 line-clamp-2 max-w-[300px]">{{ p.caption_translated || p.caption }}</div>
            }

            <!-- Scoring sections: 2-col grid for landscape, stacked for portrait -->
            <div [class.grid]="isLandscape()" [class.grid-cols-2]="isLandscape()" [class.gap-3]="isLandscape()">
              <!-- Left column (landscape) / first section (portrait): Quality -->
              <div>
                <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-1">
                  <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.quality_section' | translate }}</div>
                  <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.aesthetic' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic | fixed:1 }}</span></div>
                  @if (p.quality_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.quality_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.quality_score | fixed:1 }}</span></div>
                  }
                  @if (p.topiq_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.topiq_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.topiq_score | fixed:1 }}</span></div>
                  }
                  @if (p.face_count > 0 && p.face_quality != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_quality' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality | fixed:1 }}</span></div>
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.faces' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_count }}</span></div>
                    @if (p.face_ratio) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_ratio' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_ratio * 100 | fixed:0 }}%</span></div>
                    }
                    @if (p.face_sharpness != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.eye_sharpness != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.eye_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.eye_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.face_confidence != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_confidence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_confidence * 100 | fixed:0 }}%</span></div>
                    }
                  }
                  @if (p.tech_sharpness != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.tech_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.tech_sharpness | fixed:1 }}</span></div>
                  }
                  @if (p.aesthetic_iaa != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.aesthetic_iaa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic_iaa | fixed:1 }}</span></div>
                  }
                  @if (p.face_quality_iqa != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_quality_iqa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality_iqa | fixed:1 }}</span></div>
                  }
                  @if (p.liqe_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.liqe_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.liqe_score | fixed:1 }}</span></div>
                  }
                </div>
              </div>

              <!-- Right column (landscape) / remaining sections (portrait): Composition + Saliency -->
              <div>
                <!-- Composition section -->
                <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-1"
                  [class.mt-2]="!isLandscape()"
                >
                  <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.composition_section' | translate }}</div>
                  @if (p.comp_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.composition' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.comp_score | fixed:1 }}</span></div>
                  }
                  @if (p.composition_pattern) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
                  }
                  @if (p.power_point_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.power_points' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.power_point_score | fixed:1 }}</span></div>
                  }
                  @if (p.leading_lines_score != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.leading_lines' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.leading_lines_score | fixed:1 }}</span></div>
                  }
                  @if (p.isolation_bonus != null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.isolation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.isolation_bonus | fixed:1 }}</span></div>
                  }
                </div>

                <!-- Subject Saliency section -->
                @if (p.subject_sharpness != null || p.subject_prominence != null || p.subject_placement != null || p.bg_separation != null) {
                  <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-2">
                    <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.saliency_section' | translate }}</div>
                    @if (p.subject_sharpness != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.subject_prominence != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_prominence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_prominence | fixed:1 }}</span></div>
                    }
                    @if (p.subject_placement != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_placement' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_placement | fixed:1 }}</span></div>
                    }
                    @if (p.bg_separation != null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.bg_separation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.bg_separation | fixed:1 }}</span></div>
                    }
                  </div>
                }
              </div>
            </div>
          </div>
        </div>

        <!-- Zone B: Technical + EXIF side-by-side -->
        <div class="grid gap-3 border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-2 text-xs leading-relaxed text-[var(--facet-tooltip-text)]"
          [class.grid-cols-2]="hasExif()"
          [class.grid-cols-1]="!hasExif()"
        >
          <!-- Technical column -->
          <div>
            <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.technical_section' | translate }}</div>
            @if (p.exposure_score != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.exposure' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.exposure_score | fixed:1 }}</span></div>
            }
            @if (p.color_score != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.color' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_score | fixed:1 }}</span></div>
            }
            @if (p.contrast_score != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.contrast' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.contrast_score | fixed:1 }}</span></div>
            }
            @if (p.dynamic_range_stops != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.dynamic_range' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.dynamic_range_stops | fixed:1 }}</span></div>
            }
            @if (p.mean_saturation != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.saturation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ (p.mean_saturation * 100) | fixed:0 }}%</span></div>
            }
            @if (p.noise_sigma != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.noise' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.noise_sigma | fixed:1 }}</span></div>
            }
            @if (p.mean_luminance != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.luminance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.mean_luminance * 100 | fixed:0 }}%</span></div>
            }
            @if (p.histogram_spread != null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.histogram_spread' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.histogram_spread | fixed:1 }}</span></div>
            }
          </div>

          <!-- EXIF column -->
          @if (hasExif()) {
            <div>
              <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.exif_section' | translate }}</div>
              @if (p.camera_model) {
                <div class="flex justify-between gap-4"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.camera' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium truncate">{{ p.camera_model }}</span></div>
              }
              @if (p.lens_model) {
                <div class="flex justify-between gap-4"><span class="text-[var(--facet-tooltip-text-secondary)] shrink-0">{{ 'tooltip.lens' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium truncate">{{ p.lens_model }}</span></div>
              }
              @if (p.focal_length) {
                <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.focal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.focal_length }}mm</span></div>
              }
              @if (p.f_stop) {
                <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.aperture' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">f/{{ p.f_stop }}</span></div>
              }
              @if (p.shutter_speed) {
                <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.shutter' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.shutter_speed | shutterSpeed }}</span></div>
              }
              @if (p.iso) {
                <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.iso' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.iso }}</span></div>
              }
            </div>
          }
        </div>

        <!-- Zone C: Tags (full width) -->
        @if (p.tags_list.length) {
          <div class="flex gap-1 flex-wrap mt-2 pt-1.5 border-t border-[var(--facet-tooltip-divider)]">
            @for (tag of p.tags_list; track tag) {
              <span class="px-1.5 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded text-[10px]">{{ tag }}</span>
            }
          </div>
        }

      </div>
    }
  `,
})
export class PhotoTooltipComponent {
  readonly photo = input<Photo | null>(null);
  readonly x = input(0);
  readonly y = input(0);
  readonly flipped = input(false);

  /** Whether the photo is landscape orientation (wider than tall). */
  readonly isLandscape = computed(() => {
    const p = this.photo();
    return p ? p.image_width > p.image_height : false;
  });

  /** Whether any EXIF field is present. */
  readonly hasExif = computed(() => {
    const p = this.photo();
    if (!p) return false;
    return !!(p.camera_model || p.lens_model || p.focal_length || p.f_stop || p.shutter_speed || p.iso);
  });
}
