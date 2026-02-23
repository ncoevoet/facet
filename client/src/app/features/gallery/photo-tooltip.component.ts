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
        class="fixed z-[1000] pointer-events-none flex items-start gap-3 bg-neutral-900/[.97] backdrop-blur-sm p-2.5 rounded-xl shadow-2xl border border-neutral-700"
        [class.flex-col]="isLandscape()"
        [style.left.px]="x()"
        [style.top.px]="y()"
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

        <!-- Details panel -->
        <div class="text-xs leading-relaxed text-neutral-300 min-w-[240px] max-w-[260px]"
          [class.max-w-none]="isLandscape()"
          [class.w-full]="isLandscape()"
        >
          <!-- Filename -->
          <div class="font-semibold text-neutral-200 truncate">{{ p.filename }}</div>

          <!-- Date -->
          @if (p.date_taken) {
            <div class="text-neutral-500 text-[11px]">{{ p.date_taken }}</div>
          }

          <!-- Category + aggregate + star rating -->
          <div class="text-[var(--mat-sys-primary)] font-semibold mb-1.5">
            @if (p.star_rating) {
              <span class="text-yellow-400">★{{ p.star_rating }}</span>
            }
            [{{ p.category | categoryLabel }}] {{ 'tooltip.aggregate' | translate }}: {{ p.aggregate | fixed:1 }}
          </div>

          <!-- Quality section -->
          <div class="border-t border-neutral-700 pt-1.5 mt-1">
            <div class="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">{{ 'tooltip.quality_section' | translate }}</div>
            <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.aesthetic' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic | fixed:1 }}</span></div>
            @if (p.quality_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.quality_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.quality_score | fixed:1 }}</span></div>
            }
            @if (p.topiq_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.topiq_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.topiq_score | fixed:1 }}</span></div>
            }
            @if (p.face_count > 0 && p.face_quality != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.face_quality' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality | fixed:1 }}</span></div>
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.faces' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_count }}</span></div>
              @if (p.face_ratio) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.face_ratio' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_ratio * 100 | fixed:0 }}%</span></div>
              }
              @if (p.face_sharpness != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.face_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_sharpness | fixed:1 }}</span></div>
              }
              @if (p.eye_sharpness != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.eye_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.eye_sharpness | fixed:1 }}</span></div>
              }
              @if (p.face_confidence != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.face_confidence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_confidence * 100 | fixed:0 }}%</span></div>
              }
            }
            @if (p.tech_sharpness != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.tech_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.tech_sharpness | fixed:1 }}</span></div>
            }
            @if (p.aesthetic_iaa != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.aesthetic_iaa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic_iaa | fixed:1 }}</span></div>
            }
            @if (p.face_quality_iqa != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.face_quality_iqa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality_iqa | fixed:1 }}</span></div>
            }
            @if (p.liqe_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.liqe_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.liqe_score | fixed:1 }}</span></div>
            }
          </div>

          <!-- Composition section -->
          <div class="border-t border-neutral-700 pt-1.5 mt-2">
            <div class="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">{{ 'tooltip.composition_section' | translate }}</div>
            @if (p.comp_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.composition' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.comp_score | fixed:1 }}</span></div>
            }
            @if (p.composition_pattern) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
            }
            @if (p.power_point_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.power_points' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.power_point_score | fixed:1 }}</span></div>
            }
            @if (p.leading_lines_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.leading_lines' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.leading_lines_score | fixed:1 }}</span></div>
            }
            @if (p.isolation_bonus != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.isolation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.isolation_bonus | fixed:1 }}</span></div>
            }
          </div>

          <!-- Subject Saliency section -->
          @if (p.subject_sharpness != null || p.subject_prominence != null || p.subject_placement != null || p.bg_separation != null) {
            <div class="border-t border-neutral-700 pt-1.5 mt-2">
              <div class="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">{{ 'tooltip.saliency_section' | translate }}</div>
              @if (p.subject_sharpness != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.subject_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_sharpness | fixed:1 }}</span></div>
              }
              @if (p.subject_prominence != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.subject_prominence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_prominence | fixed:1 }}</span></div>
              }
              @if (p.subject_placement != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.subject_placement' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_placement | fixed:1 }}</span></div>
              }
              @if (p.bg_separation != null) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.bg_separation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.bg_separation | fixed:1 }}</span></div>
              }
            </div>
          }

          <!-- Technical section -->
          <div class="border-t border-neutral-700 pt-1.5 mt-2">
            <div class="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">{{ 'tooltip.technical_section' | translate }}</div>
            @if (p.exposure_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.exposure' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.exposure_score | fixed:1 }}</span></div>
            }
            @if (p.color_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.color' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_score | fixed:1 }}</span></div>
            }
            @if (p.contrast_score != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.contrast' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.contrast_score | fixed:1 }}</span></div>
            }
            @if (p.dynamic_range_stops != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.dynamic_range' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.dynamic_range_stops | fixed:1 }}</span></div>
            }
            @if (p.mean_saturation != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.saturation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ (p.mean_saturation * 100) | fixed:0 }}%</span></div>
            }
            @if (p.noise_sigma != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.noise' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.noise_sigma | fixed:1 }}</span></div>
            }
            @if (p.mean_luminance != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.luminance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.mean_luminance * 100 | fixed:0 }}%</span></div>
            }
            @if (p.histogram_spread != null) {
              <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.histogram_spread' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.histogram_spread | fixed:1 }}</span></div>
            }
          </div>

          <!-- EXIF section -->
          @if (p.camera_model || p.lens_model || p.focal_length || p.shutter_speed || p.iso) {
            <div class="border-t border-neutral-700 pt-1.5 mt-2">
              <div class="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">{{ 'tooltip.exif_section' | translate }}</div>
              @if (p.camera_model) {
                <div class="flex justify-between gap-4"><span class="text-neutral-400">{{ 'tooltip.camera' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium truncate">{{ p.camera_model }}</span></div>
              }
              @if (p.lens_model) {
                <div class="flex justify-between gap-4"><span class="text-neutral-400 shrink-0">{{ 'tooltip.lens' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium truncate">{{ p.lens_model }}</span></div>
              }
              @if (p.focal_length) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.focal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.focal_length }}mm</span></div>
              }
              @if (p.shutter_speed) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.shutter' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.shutter_speed | shutterSpeed }}</span></div>
              }
              @if (p.iso) {
                <div class="flex justify-between"><span class="text-neutral-400">{{ 'tooltip.iso' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.iso }}</span></div>
              }
            </div>
          }

          <!-- Tags -->
          @if (p.tags_list.length) {
            <div class="flex gap-1 flex-wrap mt-2 pt-1.5 border-t border-neutral-700">
              @for (tag of p.tags_list; track tag) {
                <span class="px-1.5 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded text-[10px]">{{ tag }}</span>
              }
            </div>
          }
        </div>
      </div>
    }
  `,
})
export class PhotoTooltipComponent {
  readonly photo = input<Photo | null>(null);
  readonly x = input(0);
  readonly y = input(0);

  /** Whether the photo is landscape orientation (wider than tall). */
  readonly isLandscape = computed(() => {
    const p = this.photo();
    return p ? p.image_width > p.image_height : false;
  });
}
