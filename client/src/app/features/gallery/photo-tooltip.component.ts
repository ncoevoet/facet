import { Component, DestroyRef, Pipe, PipeTransform, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { catchError, of } from 'rxjs';
import { Photo, PhotoSet } from '../../shared/models/photo.model';
import { ApiService } from '../../core/services/api.service';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../shared/pipes/shutter-speed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { IsLensNamePipe } from '../../shared/pipes/is-lens-name.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { EvOffsetPipe } from './burst-culling.pipes';
import { MomentLabelPipe } from '../scenes/scenes.pipes';
import { aspectOf } from './gallery-rows.util';
import { HistogramComponent, HISTOGRAM_TOOLTIP_HEIGHT } from '../../shared/components/histogram/histogram.component';
import { HistogramMode } from '../../shared/utils/histogram';

/** How long the pointer must rest on a photo before the tooltip fetches the
 *  frame count + EV span for its set. Kind and this frame's own EV offset are
 *  already on the Photo object and render with zero delay -- only the
 *  cross-photo fields (`GET /api/photo/set`) are worth debouncing across a
 *  dense gallery where the pointer crosses many tiles per second. */
const SET_INFO_DWELL_MS = 300;

// Intentionally keeps literal i18n keys instead of the shared I18N constants: this
// spec renders right after a Leaflet map spec, and the Angular Vitest builder shares
// one module registry per worker -- the map spec's module mock resets it and nulls
// this component's I18N import binding. Excluded in client/scripts/migrate-i18n.mjs.

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
  imports: [
    MatIconModule, FixedPipe, ShutterSpeedPipe, TranslatePipe, ThumbnailUrlPipe, PersonThumbnailUrlPipe,
    CategoryLabelPipe, IsLensNamePipe, PhotoSetKindIconPipe, PhotoSetKindLabelPipe, EvOffsetPipe,
    MomentLabelPipe, HistogramComponent,
  ],
  template: `
    @if (photo(); as p) {
      <!-- The class list stays a literal string: Tailwind only generates a
           utility it can see in the source, and an arbitrary value written as an
           escaped class binding is invisible to it (z-[1000] silently vanished
           that way). Docking overrides it through style bindings instead. -->
      <div
        class="fixed z-[1000] pointer-events-none flex flex-col backdrop-blur-sm p-2.5 rounded-xl shadow-2xl"
        style="background: var(--facet-tooltip-bg); border: 1px solid var(--facet-tooltip-border)"
        [style.position]="docked() ? 'static' : null"
        [style.pointer-events]="showInteractiveControls() ? 'auto' : null"
        [style.width]="docked() ? '100%' : null"
        [style.left.px]="docked() ? null : x()"
        [style.top.px]="docked() ? null : y()"
      >
        <!-- Zone A: Image + Scoring sections. The floating tooltip puts a
             portrait photo beside its numbers to stay within the viewport; the
             docked rail is a fixed narrow column, where that split leaves both
             halves too thin to read, so it always stacks. -->
        <div class="flex items-start gap-3"
          [class.flex-col]="isLandscape() || docked()"
          [class.flex-row-reverse]="!isLandscape() && !docked() && flipped()"
        >
          <!-- Image preview -->
          <img
            [src]="p.path | thumbnailUrl:640"
            [alt]="p.filename"
            class="rounded-md object-contain shrink-0"
            [class.max-h-[40vh]]="!isLandscape() && !docked()"
            [class.w-full]="isLandscape() || docked()"
            [class.max-h-[28vh]]="isLandscape() && !docked()"
            [class.max-h-[45vh]]="docked()"
          />

          <!-- Scoring panel -->
          <div class="text-xs leading-relaxed text-[var(--facet-tooltip-text)]"
            [class.min-w-[240px]]="!isLandscape() && !docked()"
            [class.max-w-[260px]]="!isLandscape() && !docked()"
            [class.w-full]="isLandscape() || docked()"
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

            <!-- Narrative moment (with confidence) -->
            @if (p.narrative_moment | momentLabel; as ml) {
              <div class="text-xs mb-1.5 flex items-center gap-1.5">
                <span class="text-[var(--mat-sys-primary)] font-medium">✦ {{ ml }}</span>
                @if (p.narrative_moment_confidence !== null && p.narrative_moment_confidence !== undefined) {
                  <span class="text-[var(--facet-tooltip-text-muted)]">{{ p.narrative_moment_confidence * 100 | fixed:0 }}%</span>
                }
              </div>
            }

            <!-- Scoring sections: 2-col grid for landscape, stacked for portrait -->
            <div [class.grid]="isLandscape()" [class.grid-cols-2]="isLandscape()" [class.gap-3]="isLandscape()">
              <!-- Left column (landscape) / first section (portrait): Quality -->
              <div>
                <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-1">
                  <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.quality_section' | translate }}</div>
                  <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.aesthetic' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic | fixed:1 }}</span></div>
                  @if (p.quality_score !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.quality_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.quality_score | fixed:1 }}</span></div>
                  }
                  @if (p.topiq_score !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.topiq_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.topiq_score | fixed:1 }}</span></div>
                  }
                  @if (p.face_count > 0 && p.face_quality !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_quality' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality | fixed:1 }}</span></div>
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.faces' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_count }}</span></div>
                    @if (p.face_ratio) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_ratio' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_ratio * 100 | fixed:0 }}%</span></div>
                    }
                    @if (p.face_sharpness !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.eye_sharpness !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.eye_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.eye_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.face_confidence !== null && p.face_confidence !== undefined) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_confidence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_confidence * 100 | fixed:0 }}%</span></div>
                    }
                  }
                  @if (p.tech_sharpness !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.tech_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.tech_sharpness | fixed:1 }}</span></div>
                  }
                  @if (p.aesthetic_iaa !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.aesthetic_iaa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic_iaa | fixed:1 }}</span></div>
                  }
                  @if (p.face_quality_iqa !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.face_quality_iqa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality_iqa | fixed:1 }}</span></div>
                  }
                  @if (p.liqe_score !== null) {
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
                  @if (p.comp_score !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.composition' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.comp_score | fixed:1 }}</span></div>
                  }
                  @if (p.composition_pattern) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
                  }
                  @if (p.power_point_score !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.power_points' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.power_point_score | fixed:1 }}</span></div>
                  }
                  @if (p.leading_lines_score !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.leading_lines' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.leading_lines_score | fixed:1 }}</span></div>
                  }
                  @if (p.isolation_bonus !== null) {
                    <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.isolation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.isolation_bonus | fixed:1 }}</span></div>
                  }
                </div>

                <!-- Subject Saliency section -->
                @if (p.subject_sharpness !== null || p.subject_prominence !== null || p.subject_placement !== null || p.bg_separation !== null) {
                  <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-2">
                    <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.saliency_section' | translate }}</div>
                    @if (p.subject_sharpness !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_sharpness | fixed:1 }}</span></div>
                    }
                    @if (p.subject_prominence !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_prominence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_prominence | fixed:1 }}</span></div>
                    }
                    @if (p.subject_placement !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.subject_placement' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_placement | fixed:1 }}</span></div>
                    }
                    @if (p.bg_separation !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.bg_separation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.bg_separation | fixed:1 }}</span></div>
                    }
                  </div>
                }

                <!-- Form facet + color harmony section -->
                @if (p.form_symmetry !== null || p.form_balance !== null || p.form_edge_entropy !== null || p.form_fractal !== null || p.color_harmony !== null) {
                  <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-2">
                    <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.form_section' | translate }}</div>
                    @if (p.form_symmetry !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.form_symmetry' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.form_symmetry | fixed:1 }}</span></div>
                    }
                    @if (p.form_balance !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.form_balance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.form_balance | fixed:1 }}</span></div>
                    }
                    @if (p.form_edge_entropy !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.form_edge_entropy' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.form_edge_entropy | fixed:1 }}</span></div>
                    }
                    @if (p.form_fractal !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.form_fractal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.form_fractal | fixed:1 }}</span></div>
                    }
                    @if (p.color_harmony !== null) {
                      <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.color_harmony' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_harmony | fixed:1 }}</span></div>
                    }
                  </div>
                }
              </div>
            </div>
          </div>
        </div>

        <!-- Zone B: Technical + EXIF side-by-side, then Set (if any) and the
             histogram stacked below, each spanning the full zone width. Set and
             the histogram used to share Technical/EXIF's grid-cols, so a set-less
             photo left the histogram in a half-width column with dead space
             beside it -- pulling them into their own block fixes that, and since
             the block's presence is decided by the synchronous setKind()
             (never by the debounced GET /api/photo/set fetch), the layout is
             correct from the very first render and never reflows once the fetch
             resolves. -->
        <div class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-2 text-xs leading-relaxed text-[var(--facet-tooltip-text)]">
        <div class="grid gap-3"
          [class.grid-cols-2]="hasExif()"
          [class.grid-cols-1]="!hasExif()"
        >
          <!-- Technical column -->
          <div>
            <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.technical_section' | translate }}</div>
            @if (p.exposure_score !== null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.exposure' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.exposure_score | fixed:1 }}</span></div>
            }
            @if (p.color_score !== null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.color' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_score | fixed:1 }}</span></div>
            }
            @if (p.contrast_score !== null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.contrast' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.contrast_score | fixed:1 }}</span></div>
            }
            @if (p.dynamic_range_stops !== null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.dynamic_range' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.dynamic_range_stops | fixed:1 }}</span></div>
            }
            @if (p.mean_saturation !== null && p.mean_saturation !== undefined) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.saturation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ (p.mean_saturation * 100) | fixed:0 }}%</span></div>
            }
            @if (p.noise_sigma !== null) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.noise' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.noise_sigma | fixed:1 }}</span></div>
            }
            @if (p.mean_luminance !== null && p.mean_luminance !== undefined) {
              <div class="flex justify-between"><span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'tooltip.luminance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.mean_luminance * 100 | fixed:0 }}%</span></div>
            }
            @if (p.histogram_spread !== null) {
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
              @if (p.lens_model && (p.lens_model | isLensName)) {
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

          <!-- Set (bracket/panorama/hdr_panorama/burst/duplicate). Kind and this
               frame's own EV offset are already on the photo object and render
               instantly; frame count and EV span come from a debounced, dwell-
               delayed GET /api/photo/set (see the constructor) and fill in once
               it resolves -- never blocking the rest of the bubble. Sibling
               thumbnails are docked-only: the rail is parked and reachable,
               while reaching for one in the floating hover bubble would dismiss
               it before the click could land -- the same problem that keeps the
               histogram's mode toggle hover-only-hidden too. -->
          @if (setKind(); as kind) {
            <div class="mt-2">
              <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.set_section' | translate }}</div>
              <div class="flex items-center gap-1 flex-wrap">
                <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px] opacity-70">{{ kind | photoSetKindIcon }}</mat-icon>
                <span class="text-[var(--mat-sys-primary)] font-medium">{{ kind | photoSetKindLabel | translate }}</span>
                @if (p.sequence_ev_offset !== null && p.sequence_ev_offset !== undefined) {
                  <span class="text-[var(--facet-tooltip-text-secondary)]">{{ p.sequence_ev_offset | evOffset }}</span>
                }
              </div>
              @if (photoSet(); as set) {
                <div class="flex justify-between gap-2 text-[var(--facet-tooltip-text-secondary)]">
                  <span>{{ 'capsules.photos_count' | translate:{ count: set.count } }}</span>
                  @if (set.ev_span !== null) {
                    <span>{{ set.ev_span | fixed:1 }} EV</span>
                  }
                </div>
                @if (docked() && set.members.length) {
                  <div class="flex gap-2 flex-wrap mt-2">
                    @for (member of set.members; track member.path) {
                      <button type="button"
                              class="relative rounded-lg overflow-hidden w-14 h-14 shrink-0 cursor-pointer hover:opacity-80 transition-opacity ring-[var(--mat-sys-primary)]"
                              [class.ring-2]="member.path === p.path"
                              [attr.aria-label]="('photo_detail.set.member_position' | translate:{ position: $index + 1, count: set.members.length }) + (member.ev_offset !== null ? ', ' + (member.ev_offset | evOffset) : '')"
                              (click)="openSetMember(member.path)">
                        <img [src]="member.path | thumbnailUrl:96" alt="" class="w-full h-full object-cover" />
                        @if (member.ev_offset !== null) {
                          <span class="absolute bottom-0 inset-x-0 text-center text-[0.625rem] leading-4 bg-black/60 text-white">{{ member.ev_offset | evOffset }}</span>
                        }
                      </button>
                    }
                  </div>
                }
              }
            </div>
          }

          <!-- Histogram (stored bins, thumbnail sampling as fallback). Always
               spans the full zone width now -- see the block comment above.
               The tooltip remembers its OWN channel-mode choice, independent of
               the detail panel's, and only offers the mode toggle while pinned
               (docked rail or click-to-pin) -- moving the pointer toward it in
               hover mode would just dismiss the bubble. -->
          <div class="mt-2">
            <div class="text-[10px] text-[var(--facet-tooltip-text-muted)] uppercase tracking-wider mb-1">{{ 'tooltip.histogram' | translate }}</div>
            <app-histogram [path]="p.path" [src]="p.path | thumbnailUrl:160" [monochrome]="!!p.is_monochrome"
                           [height]="HISTOGRAM_TOOLTIP_HEIGHT" [surface]="'tooltip'"
                           [showModeToggle]="showInteractiveControls()"
                           [defaultMode]="histogramDefaultMode()"
                           [indicatorPercent]="indicatorPercent()" />
          </div>
        </div>

        <!-- Zone C: Tags (full width) -->
        @if (p.tags_list.length) {
          <div class="flex gap-1 flex-wrap mt-2 pt-1.5 border-t border-[var(--facet-tooltip-divider)]">
            @for (tag of p.tags_list; track tag) {
              <span class="px-1.5 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded text-[10px]">{{ tag }}</span>
            }
          </div>
        }

        <!-- Zone D: Person avatars. No label -- round face thumbnails are
             self-explanatory and the label was just noise competing for width
             in the rail. Clickable to filter the gallery by that person, but
             only where showInteractiveControls() holds: a plain hover bubble
             dismisses before a click could land, so an avatar there must stay
             a non-interactive image, not a button that looks clickable but
             is not. Bigger in the docked rail (w-11 = 44px, in the 40-48px
             legible-face range and a comfortable touch target) since it now
             has the width the removed label freed up; the floating bubble
             keeps the original 24px -- it is a dense scan-many-photos
             surface where large avatars would cost width against the
             scoring grid, whether or not it happens to be click-pinned. -->
        @if (p.persons.length) {
          <div class="flex items-center gap-1.5 flex-wrap mt-2 pt-1.5 border-t border-[var(--facet-tooltip-divider)]">
            @for (person of p.persons; track person.id) {
              @if (showInteractiveControls()) {
                <button type="button"
                        class="rounded-full ring-1 ring-[var(--facet-tooltip-divider)] cursor-pointer hover:opacity-80 transition-opacity overflow-hidden"
                        [class.w-11]="docked()" [class.h-11]="docked()"
                        [class.w-6]="!docked()" [class.h-6]="!docked()"
                        [attr.aria-label]="'tooltip.filter_by_person' | translate:{ name: person.name }"
                        [title]="person.name"
                        (click)="onPersonClick(person.id)">
                  <img [src]="person.id | personThumbnailUrl" [alt]="person.name" class="w-full h-full object-cover" />
                </button>
              } @else {
                <img
                  [src]="person.id | personThumbnailUrl"
                  [alt]="person.name"
                  [title]="person.name"
                  class="w-6 h-6 rounded-full object-cover ring-1 ring-[var(--facet-tooltip-divider)]"
                />
              }
            }
          </div>
        }

      </div>
    }
  `,
})
export class PhotoTooltipComponent {
  readonly photo = input<Photo | null>(null);
  /** Clipping threshold for the histogram's markers, from `viewer.clipping`.
   *  Passed in rather than read from config here so the tooltip, the detail
   *  panel and the gallery badge cannot disagree about what counts as clipped. */
  readonly indicatorPercent = input(1);
  readonly x = input(0);
  readonly y = input(0);
  readonly flipped = input(false);
  /**
   * Render docked in a column instead of floating at (x, y).
   *
   * Same content either way — what changes is that a docked panel stays in one
   * place, which is the whole point of the mode: comparing the same field
   * across photos is guesswork when the box moves with the cursor.
   */
  readonly docked = input(false);
  /**
   * Whether this bubble is held in place rather than dismissed by moving the
   * pointer -- a docked rail, or a floating bubble kept open by a click. Only
   * a pinned bubble can host the histogram's mode-toggle buttons: in plain
   * hover mode, moving the pointer toward them would dismiss the tooltip
   * before a click could ever land.
   */
  readonly pinned = input(false);
  /** House default for the tooltip's OWN histogram channel mode, from
   *  `viewer.clipping.tooltip_histogram_mode` -- independent of the detail
   *  panel's default and of the user's per-surface persisted choice. */
  readonly histogramDefaultMode = input<HistogramMode>('luma');

  /** Whether the photo is landscape orientation (wider than tall).
   *
   *  Reads `aspectOf`, not the raw dimensions: those are null for a row whose
   *  fabricated size was cleared, and the aspect it kept still answers this. */
  readonly isLandscape = computed(() => {
    const p = this.photo();
    return p ? aspectOf(p) > 1 : false;
  });

  /** Whether any EXIF field is present. */
  readonly hasExif = computed(() => {
    const p = this.photo();
    if (!p) return false;
    return !!(p.camera_model || p.lens_model || p.focal_length || p.f_stop || p.shutter_speed || p.iso);
  });

  /** The set this frame resolves into, mirroring `GET /api/photo/set`'s own
   *  precedence (sequence, then burst, then duplicate) from fields already on
   *  the photo object -- 'burst' and 'duplicate' have no `sequence_kind`
   *  counterpart, since neither is a value that column can hold. */
  protected readonly setKind = computed(() => {
    const p = this.photo();
    if (!p) return null;
    if (p.sequence_kind) return p.sequence_kind;
    if (p.burst_group_id != null) return 'burst';
    if (p.duplicate_group_id != null) return 'duplicate';
    return null;
  });

  protected readonly HISTOGRAM_TOOLTIP_HEIGHT = HISTOGRAM_TOOLTIP_HEIGHT;
  /** Whether this bubble is safe to host click targets beyond the
   *  toggle-the-photo click itself: the docked rail is always parked, and a
   *  click-pinned floating bubble does not dismiss on mouse-leave either (see
   *  onMouseLeave/hoverDriven() in photo-card.component.ts) -- only a plain
   *  hover bubble does, which is why it is excluded here. Gates the
   *  histogram's mode-toggle buttons and the person-avatar filter buttons. */
  protected readonly showInteractiveControls = computed(() => this.docked() || this.pinned());

  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private destroyed = false;
  // Bumped on every photo change so a slow response can't overwrite the set
  // info of the photo the pointer has already moved on to.
  private setGeneration = 0;

  /** Frame count + EV span for the photo's set (kind and this frame's own EV
   *  offset are already on `Photo` and need no fetch). null until the fetch
   *  resolves, or when the photo belongs to no set at all. */
  protected readonly photoSet = signal<PhotoSet | null>(null);

  constructor() {
    this.destroyRef.onDestroy(() => { this.destroyed = true; });
    effect(onCleanup => {
      const p = this.photo();
      const token = ++this.setGeneration;
      untracked(() => this.photoSet.set(null));
      if (!p || !this.setKind()) return;
      const requestedPath = p.path;
      // Dwell delay: a pointer merely crossing many tiles never fires this
      // request at all, since each new photo cancels the previous timer.
      const timer = setTimeout(() => {
        const subscription = this.api
          .get<PhotoSet>('/photo/set', { path: requestedPath })
          .pipe(catchError(() => of(null)))
          .subscribe(res => {
            if (this.destroyed || token !== this.setGeneration) return;
            this.photoSet.set(res);
          });
        onCleanup(() => subscription.unsubscribe());
      }, SET_INFO_DWELL_MS);
      onCleanup(() => clearTimeout(timer));
    });
  }

  /**
   * Open a sibling frame's own detail page (docked-panel sibling strip only).
   *
   * Chosen over swapping the panel's subject in place: every other sibling-
   * thumbnail strip in the app (photo-detail's own set block) already opens
   * the clicked frame's detail page, and a `PhotoSetMember` carries only a
   * path + EV offset -- not a full `Photo` -- so swapping in place would need
   * its own fetch anyway. One interaction for the one visual affordance, on
   * whichever surface it appears on. No `state: { photo }` pre-fetch payload
   * (unlike the gallery grid's own double-click-to-open): the destination
   * page's existing query-param fallback fetches it, same as a bookmarked link.
   */
  protected openSetMember(path: string): void {
    this.router.navigate(['/photo'], { queryParams: { path } });
  }

  /** Emits the clicked person's id, comma-list-formatted the way `person_id`
   *  filter values already are (a lone id is a valid one-element list) --
   *  see gallery-filter-sidebar.component.ts's own `ids.join(',')`. Only
   *  reachable where showInteractiveControls() renders the avatar as a
   *  button in the first place (docked rail, or a click-pinned floating
   *  bubble). The click REPLACES the current person filter rather than
   *  adding to it -- the more predictable outcome for a single click on one
   *  face -- while the sidebar's own multi-select remains the place to build
   *  up a filter across several people. */
  readonly personSelected = output<string>();

  protected onPersonClick(id: number): void {
    this.personSelected.emit(String(id));
  }
}
