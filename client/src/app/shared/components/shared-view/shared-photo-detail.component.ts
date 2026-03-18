import { Component, inject, signal, computed, OnInit, HostListener } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../models/photo.model';
import { ApiService } from '../../../core/services/api.service';
import { FixedPipe } from '../../pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../pipes/shutter-speed.pipe';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../pipes/thumbnail-url.pipe';
import { CategoryLabelPipe } from '../../../features/gallery/photo-tooltip.component';
import { IsLensNamePipe } from '../../pipes/is-lens-name.pipe';

@Component({
  selector: 'app-shared-photo-detail',
  standalone: true,
  imports: [
    MatIconModule, MatButtonModule, MatTooltipModule,
    FixedPipe, ShutterSpeedPipe, TranslatePipe, ThumbnailUrlPipe,
    CategoryLabelPipe, IsLensNamePipe,
  ],
  host: { class: 'block h-full overflow-y-auto lg:overflow-y-hidden' },
  template: `
    @if (photo(); as p) {
      <!-- Header bar -->
      <div class="flex items-center gap-2 px-1 py-1 border-b border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)]">
        <button mat-icon-button (click)="goBack()" [matTooltip]="'photo_detail.back' | translate">
          <mat-icon>arrow_back</mat-icon>
        </button>
        <span class="flex-1 truncate font-medium">{{ p.filename }}</span>
        <button mat-button (click)="download(p.path)" [matTooltip]="'photo_detail.download' | translate">
          <mat-icon>download</mat-icon>
          {{ 'photo_detail.download' | translate }}
        </button>
      </div>

      <!-- Main content: image + info -->
      <div class="flex flex-col lg:flex-row lg:h-[calc(100%-49px)] lg:overflow-hidden">
        <!-- Image panel -->
        <div class="shrink-0 lg:h-auto lg:flex-1 flex items-center justify-center bg-black lg:min-h-0 relative">
          <img
            [src]="p.path | thumbnailUrl:640"
            [alt]="p.filename"
            class="w-full lg:max-w-full lg:max-h-full object-contain transition-opacity duration-300"
            [class.opacity-0]="fullImageLoaded()"
          />
          <img
            [src]="fullImageUrl()"
            [alt]="p.filename"
            class="absolute inset-0 w-full h-full object-contain transition-opacity duration-300"
            [class.opacity-0]="!fullImageLoaded()"
            (load)="onFullImageLoad()"
          />
        </div>

        <!-- Info panel -->
        <div class="lg:w-[380px] lg:shrink-0 lg:overflow-y-auto p-4 space-y-4 text-sm text-[var(--mat-sys-on-surface)]">
          <!-- Filename + Date + Category + Aggregate -->
          <div>
            <div class="font-semibold text-lg">{{ p.filename }}</div>
            @if (p.date_taken) {
              <div class="text-[var(--mat-sys-on-surface-variant)] text-xs">{{ p.date_taken }}</div>
            }
            <div class="flex items-center gap-2 mt-1">
              @if (p.category) {
                <span class="px-2 py-0.5 bg-[var(--mat-sys-primary-container)] text-[var(--mat-sys-on-primary-container)] rounded-full text-xs font-medium">{{ p.category | categoryLabel }}</span>
              }
              <span class="text-[var(--mat-sys-primary)] font-semibold ml-auto">{{ p.aggregate | fixed:1 }}</span>
            </div>
          </div>

          <!-- Quality section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.quality' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aesthetic' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic | fixed:1 }}</span></div>
              @if (p.quality_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.quality_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.quality_score | fixed:1 }}</span></div>
              }
              @if (p.topiq_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.topiq_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.topiq_score | fixed:1 }}</span></div>
              }
              @if (p.tech_sharpness != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.tech_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.tech_sharpness | fixed:1 }}</span></div>
              }
              @if (p.face_count > 0 && p.face_quality != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_quality' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality | fixed:1 }}</span></div>
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.faces' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_count }}</span></div>
                @if (p.face_ratio) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_ratio' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_ratio * 100 | fixed:0 }}%</span></div>
                }
                @if (p.face_sharpness != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_sharpness | fixed:1 }}</span></div>
                }
                @if (p.eye_sharpness != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.eye_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.eye_sharpness | fixed:1 }}</span></div>
                }
                @if (p.face_confidence != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_confidence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_confidence * 100 | fixed:0 }}%</span></div>
                }
              }
              @if (p.aesthetic_iaa != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aesthetic_iaa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.aesthetic_iaa | fixed:1 }}</span></div>
              }
              @if (p.face_quality_iqa != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.face_quality_iqa' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.face_quality_iqa | fixed:1 }}</span></div>
              }
              @if (p.liqe_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.liqe_score' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.liqe_score | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- Composition section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.composition' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              @if (p.comp_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.composition' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.comp_score | fixed:1 }}</span></div>
              }
              @if (p.composition_pattern) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.pattern' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ ('composition_patterns.' + p.composition_pattern) | translate }}</span></div>
              }
              @if (p.power_point_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.power_points' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.power_point_score | fixed:1 }}</span></div>
              }
              @if (p.leading_lines_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.leading_lines' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.leading_lines_score | fixed:1 }}</span></div>
              }
              @if (p.isolation_bonus != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.isolation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.isolation_bonus | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- Subject Saliency section -->
          @if (p.subject_sharpness != null || p.subject_prominence != null || p.subject_placement != null || p.bg_separation != null) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.saliency' | translate }}</div>
              <div class="flex flex-col gap-0.5">
                @if (p.subject_sharpness != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_sharpness' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_sharpness | fixed:1 }}</span></div>
                }
                @if (p.subject_prominence != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_prominence' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_prominence | fixed:1 }}</span></div>
                }
                @if (p.subject_placement != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.subject_placement' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.subject_placement | fixed:1 }}</span></div>
                }
                @if (p.bg_separation != null) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.bg_separation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.bg_separation | fixed:1 }}</span></div>
                }
              </div>
            </div>
          }

          <!-- Technical section -->
          <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
            <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.technical' | translate }}</div>
            <div class="flex flex-col gap-0.5">
              @if (p.exposure_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.exposure' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.exposure_score | fixed:1 }}</span></div>
              }
              @if (p.color_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.color' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.color_score | fixed:1 }}</span></div>
              }
              @if (p.contrast_score != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.contrast' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.contrast_score | fixed:1 }}</span></div>
              }
              @if (p.dynamic_range_stops != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.dynamic_range' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.dynamic_range_stops | fixed:1 }}</span></div>
              }
              @if (p.mean_saturation != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.saturation' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ (p.mean_saturation * 100) | fixed:0 }}%</span></div>
              }
              @if (p.noise_sigma != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.noise' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.noise_sigma | fixed:1 }}</span></div>
              }
              @if (p.mean_luminance != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.luminance' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.mean_luminance * 100 | fixed:0 }}%</span></div>
              }
              @if (p.histogram_spread != null) {
                <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.histogram_spread' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.histogram_spread | fixed:1 }}</span></div>
              }
            </div>
          </div>

          <!-- EXIF section -->
          @if (hasExif()) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.exif' | translate }}</div>
              <div class="flex flex-col gap-0.5">
                @if (p.camera_model) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.camera' | translate }}</span><span class="truncate">{{ p.camera_model }}</span></div>
                }
                @if (p.lens_model && (p.lens_model | isLensName)) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.lens' | translate }}</span><span class="truncate">{{ p.lens_model }}</span></div>
                }
                @if (p.focal_length) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.focal' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.focal_length }}mm</span></div>
                }
                @if (p.f_stop) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.aperture' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">f/{{ p.f_stop }}</span></div>
                }
                @if (p.shutter_speed) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.shutter' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.shutter_speed | shutterSpeed }}</span></div>
                }
                @if (p.iso) {
                  <div class="flex justify-between items-baseline gap-2"><span class="text-[var(--mat-sys-on-surface-variant)]">{{ 'tooltip.iso' | translate }}</span><span class="text-[var(--mat-sys-primary)] font-medium">{{ p.iso }}</span></div>
                }
              </div>
            </div>
          }

          <!-- Tags section -->
          @if (p.tags_list.length) {
            <div class="border-t border-[var(--mat-sys-outline-variant)] pt-3">
              <div class="text-[0.625rem] uppercase tracking-wider text-[var(--mat-sys-on-surface-variant)] mb-2">{{ 'photo_detail.tags' | translate }}</div>
              <div class="flex gap-1.5 flex-wrap">
                @for (tag of p.tags_list; track tag) {
                  <span class="px-2 py-0.5 bg-[var(--facet-accent-badge)] text-[var(--facet-accent-text)] rounded-full text-xs">{{ tag }}</span>
                }
              </div>
            </div>
          }
        </div>
      </div>
    } @else {
      <div class="flex items-center justify-center h-full">
        <mat-icon class="!text-4xl text-[var(--mat-sys-on-surface-variant)]">hourglass_empty</mat-icon>
      </div>
    }
  `,
})
export class SharedPhotoDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);

  protected readonly photo = signal<Photo | null>(null);
  protected readonly fullImageLoaded = signal(false);

  protected readonly fullImageUrl = computed(() => {
    const p = this.photo();
    return p ? this.api.imageUrl(p.path) : '';
  });

  protected readonly hasExif = computed(() => {
    const p = this.photo();
    if (!p) return false;
    return !!(p.camera_model || p.lens_model || p.focal_length || p.f_stop || p.shutter_speed || p.iso);
  });

  private get token(): string {
    return this.route.snapshot.queryParamMap.get('token') ?? '';
  }

  private get sharedBasePath(): string {
    // Determine if we came from album or person by checking URL segments
    const url = this.route.snapshot.url;
    // url segments: ['shared', 'album'|'person', ':id', 'photo']
    const entityType = url[1]?.path ?? 'album';
    const entityId = url[2]?.path ?? '';
    return `/shared/${entityType}/${entityId}`;
  }

  async ngOnInit(): Promise<void> {
    const statePhoto = history.state?.['photo'] as Photo | undefined;
    if (statePhoto) {
      this.photo.set(statePhoto);
    } else {
      // Try loading from API
      const path = this.route.snapshot.queryParamMap.get('path');
      if (path) {
        try {
          const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }));
          if (!photo.tags_list) {
            photo.tags_list = photo.tags ? photo.tags.split(',').map(t => t.trim()) : [];
          }
          if (!photo.persons) {
            photo.persons = [];
          }
          this.photo.set(photo);
        } catch {
          this.navigateBack();
        }
      } else {
        this.navigateBack();
      }
    }
  }

  @HostListener('document:keydown.escape')
  protected goBack(): void {
    this.navigateBack();
  }

  protected onFullImageLoad(): void {
    this.fullImageLoaded.set(true);
  }

  protected download(path: string): void {
    const a = document.createElement('a');
    a.href = `/api/download?path=${encodeURIComponent(path)}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  private navigateBack(): void {
    this.router.navigate([this.sharedBasePath], { queryParams: { token: this.token } });
  }
}
