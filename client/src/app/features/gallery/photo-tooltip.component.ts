import { Component, DestroyRef, Pipe, PipeTransform, computed, effect, inject, input, output, signal, untracked, viewChild, ElementRef, ChangeDetectionStrategy } from '@angular/core';
import { NgTemplateOutlet, TitleCasePipe } from '@angular/common';
import { Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { catchError, of } from 'rxjs';
import { Photo, PhotoSet, hasExifFields } from '../../shared/models/photo.model';
import { ApiService } from '../../core/services/api.service';
import { FixedPipe } from '../../shared/pipes/fixed.pipe';
import { ShutterSpeedPipe } from '../../shared/pipes/shutter-speed.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PhotoSetKindIconPipe, PhotoSetKindLabelPipe } from '../../shared/pipes/photo-set-kind.pipe';
import { EvOffsetPipe } from './burst-culling.pipes';
import { MomentLabelPipe } from '../scenes/scenes.pipes';
import { aspectOf } from './gallery-rows.util';
import { GalleryStore } from './gallery.store';
import { HISTOGRAM_TOOLTIP_HEIGHT } from '../../shared/components/histogram/histogram.component';
import { HistogramMode } from '../../shared/utils/histogram';
import { PhotoMetricsTabsComponent } from '../../shared/components/photo-metrics-tabs/photo-metrics-tabs.component';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { PhotoAssessmentComponent } from '../../shared/components/photo-assessment/photo-assessment.component';

/** How long the pointer must rest on a photo before the tooltip fetches the
 *  frame count + EV span for its set. Kind and this frame's own EV offset are
 *  already on the Photo object and render with zero delay -- only the
 *  cross-photo fields (`GET /api/photo/set`) are worth debouncing across a
 *  dense gallery where the pointer crosses many tiles per second. */
const SET_INFO_DWELL_MS = 300;

/** The scores the floating bubble keeps: one per question a glance asks -- is it
 *  pleasing, well composed, sharp, well exposed. */
const KEY_SCORES = [
  { field: 'aesthetic', label: 'tooltip.aesthetic' },
  { field: 'comp_score', label: 'tooltip.composition' },
  { field: 'tech_sharpness', label: 'tooltip.tech_sharpness' },
  { field: 'exposure_score', label: 'tooltip.exposure' },
] as const;

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
    MatIconModule, NgTemplateOutlet, FixedPipe, ShutterSpeedPipe, TranslatePipe, ThumbnailUrlPipe, PersonThumbnailUrlPipe,
    CategoryLabelPipe, PhotoSetKindIconPipe, PhotoSetKindLabelPipe, EvOffsetPipe,
    MomentLabelPipe, PhotoMetricsTabsComponent, CaptureDatePipe, PhotoAssessmentComponent,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    @if (photo(); as p) {
      <!-- The class list stays a literal string: Tailwind only generates a
           utility it can see in the source, and an arbitrary value written as an
           escaped class binding is invisible to it (z-[1000] silently vanished
           that way). Docking overrides it through style bindings instead. -->
      <div #root
        class="fixed z-[1000] pointer-events-none flex flex-col backdrop-blur-sm p-2.5 rounded-xl shadow-2xl"
        [class.max-h-[calc(100vh-2rem)]]="!docked()"
        [class.overflow-y-auto]="!docked()"
        [style.position]="docked() ? 'static' : null"
        [style.pointer-events]="showInteractiveControls() ? 'auto' : null"
        [style.width]="docked() ? '100%' : null"
        [style.background]="docked() ? 'transparent' : 'var(--facet-tooltip-bg)'"
        [style.border]="docked() ? 'none' : '1px solid var(--facet-tooltip-border)'"
        [style.border-radius]="docked() ? '0' : null"
        [style.box-shadow]="docked() ? 'none' : null"
        [style.left.px]="docked() ? null : left()"
        [style.top.px]="docked() ? null : top()"
      >
        <!-- Zone A: Image + Scoring sections. The floating tooltip puts a
             portrait photo beside its numbers to stay within the viewport; the
             docked rail is a fixed narrow column, where that split leaves both
             halves too thin to read, so it always stacks. -->
        <div class="flex items-start gap-3"
          [class.flex-col]="isLandscape() || docked()"
          [class.flex-row-reverse]="!isLandscape() && !docked() && flipped()"
        >
          <!-- Image preview. Sized by its own aspect (max-w-full + w-auto) rather
               than stretched and letterboxed, so the box is the picture and the
               rounded corners show on every orientation. -->
          <img
            [src]="p.path | thumbnailUrl:640:p.preview_revision"
            [alt]="p.filename"
            class="rounded-md shrink-0 max-w-full w-auto h-auto"
            [class.self-center]="docked()"
            [class.max-h-[40vh]]="!isLandscape() && !docked()"
            [class.max-h-[28vh]]="isLandscape() && !docked()"
            [class.max-h-[32dvh]]="docked()"
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
                data-capture-date>{{ p.date_taken | captureDate }}</span>
              }
            </div>

            <!-- Category + aggregate placed in the library like photo detail's,
               with the stars on their own line. -->
            @if (p.category) { <div class="flex items-center gap-2 mt-1 mb-1.5">
              <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--mat-sys-primary-container)] text-[var(--mat-sys-on-primary-container)] truncate">{{ p.category | categoryLabel }}</span>
            </div> }
            @if (!docked()) { <app-photo-assessment [photo]="p" [range]="store.metricRangesByColumn()['aggregate']" /> }
            @if (p.star_rating) {
              <div class="flex items-center gap-0.5 mb-1.5 text-yellow-400" role="img"
                   [attr.aria-label]="'rating.stars_out_of_five' | translate:{ stars: p.star_rating }">
                @for (star of stars; track star) {
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">{{ star <= p.star_rating ? 'star' : 'star_border' }}</mat-icon>
                }
              </div>
            }

            <!-- Caption (after score) -->
            @if (p.caption_translated || p.caption) {
              <!-- w-0 + min-w-full: the caption wraps inside the width the photo and
                   scores already give the bubble instead of widening it. -->
              <div class="w-0 min-w-full text-xs italic text-[var(--facet-tooltip-text-muted)] mb-1.5">{{ p.caption_translated || p.caption }}</div>
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

            <!-- Floating: a glance, not the full sheet -- four fixed scores and one
                 EXIF line. Every other metric lives in the side
                 panel and photo detail, which the docked rail renders below. -->
            @if (!docked()) {
              <div data-floating-key-scores class="border-t border-[var(--facet-tooltip-divider)] pt-1.5 mt-1">
                @for (row of KEY_SCORES; track row.field) {
                  @if (p[row.field] !== null && p[row.field] !== undefined) {
                    <div class="flex items-baseline gap-2">
                      <span class="text-[var(--facet-tooltip-text-secondary)]">{{ row.label | translate }}</span>
                      <span class="ml-auto text-[var(--mat-sys-primary)] font-medium tabular-nums">{{ p[row.field] | fixed:1 }}</span>
                    </div>
                  }
                }
              </div>
              @if (hasExif()) {
                <div class="mt-1.5 truncate text-[var(--facet-tooltip-text-secondary)] [&>span+span]:before:content-['_·_']">
                  @if (p.camera_model) {<span>{{ p.camera_model }}</span>}
                  @if (p.focal_length) {<span>{{ p.focal_length }}mm</span>}
                  @if (p.f_stop) {<span>f/{{ p.f_stop }}</span>}
                  @if (p.shutter_speed) {<span>{{ p.shutter_speed | shutterSpeed }}</span>}
                  @if (p.iso) {<span>ISO {{ p.iso }}</span>}
                </div>
              }
            }
            @if (!isLandscape() && !docked()) {
              <ng-container [ngTemplateOutlet]="details" />
            }
          </div>
        </div>
        @if (isLandscape() || docked()) {
          <ng-container [ngTemplateOutlet]="details" />
        }

        <!-- Zones B-D sit below the photo, except in a floating portrait bubble,
             where they join the column beside it so nothing spans under a tall
             image. -->
        <ng-template #details>
        <!-- Zone B: the docked rail's metric tabs, then the set strip; the floating
             bubble keeps only the set, its scores having been reduced above. -->
        @if (docked()) {
          <!-- Photo detail's metric tabs, sharing its remembered tab. -->
          <app-photo-metrics-tabs class="text-xs text-[var(--facet-tooltip-text)]" [photo]="p" [ranges]="store.metricRangesByColumn()"
                                  [populated]="store.config()?.populated_scores"
                                  [histogramSrcSize]="160" [histogramHeight]="HISTOGRAM_TOOLTIP_HEIGHT"
                                  [histogramSurface]="'tooltip'" [histogramDefaultMode]="histogramDefaultMode()"
                                  [indicatorPercent]="indicatorPercent()" />
        }
        <!-- Set (bracket/panorama/hdr_panorama/burst/duplicate). Kind and this
             frame's own EV offset are already on the photo object and render
             instantly; frame count and EV span come from a debounced, dwell-
             delayed GET /api/photo/set (see the constructor) and fill in once
             it resolves -- never blocking the rest of the bubble. Sibling
             thumbnails only in the docked panel: reaching for one in the
             floating hover bubble would dismiss it before the click could land. -->
        @if (setKind(); as kind) {
          <div class="mt-2 text-xs text-[var(--facet-tooltip-text)]" data-testid="tooltip-set">
            <div class="flex flex-wrap items-center gap-1.5">
              <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px] opacity-70" aria-hidden="true">{{ kind | photoSetKindIcon }}</mat-icon>
              <span class="text-[var(--mat-sys-primary)] font-medium">{{ kind | photoSetKindLabel | translate }}</span>
              @if (photoSet(); as set) {
                <span class="text-[var(--facet-tooltip-text-secondary)]">{{ 'capsules.photos_count' | translate:{ count: set.count } }}</span>
                @if (set.ev_span !== null) {
                  <span class="text-[var(--facet-tooltip-text-secondary)]">{{ set.ev_span | fixed:1 }} EV</span>
                }
              }
              @if (p.sequence_ev_offset !== null && p.sequence_ev_offset !== undefined) {
                <span class="ml-auto text-[var(--facet-tooltip-text-secondary)]">{{ p.sequence_ev_offset | evOffset }}</span>
              }
            </div>
            @if (photoSet(); as set) {
              @if (docked() && set.members.length) {
                <div class="flex gap-2 flex-wrap mt-2">
                  @for (member of set.members; track member.path) {
                    <button type="button"
                            class="relative rounded-lg overflow-hidden w-14 h-14 shrink-0 cursor-pointer hover:opacity-80 transition-opacity ring-[var(--mat-sys-primary)]"
                            [class.ring-2]="member.path === p.path"
                            [attr.aria-label]="('photo_detail.set.member_position' | translate:{ position: $index + 1, count: set.members.length }) + (member.ev_offset !== null ? ', ' + (member.ev_offset | evOffset) : '')"
                            (click)="openSetMember(member.path)">
                      <img [src]="member.path | thumbnailUrl:96:member.preview_revision" alt="" class="w-full h-full object-cover" />
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

        <!-- Zone C: Tags (full width) -->
        @if (p.tags_list.length) {
          <div class="flex gap-1 flex-wrap mt-2 pt-1.5 border-[var(--facet-tooltip-divider)]" [class.border-t]="!docked()">
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
          <div class="flex items-center gap-1.5 flex-wrap mt-2 pt-1.5 border-[var(--facet-tooltip-divider)]" [class.border-t]="!docked()">
            @for (person of p.persons; track person.id) {
              @if (personLinks() && showInteractiveControls()) {
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
        </ng-template>

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
  /** False renders person avatars as plain images instead of filter buttons. */
  readonly personLinks = input(true);
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
    return hasExifFields(p);
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
  protected readonly KEY_SCORES = KEY_SCORES;
  protected readonly stars: readonly number[] = [1, 2, 3, 4, 5];
  /** Whether this bubble is safe to host click targets beyond the
   *  toggle-the-photo click itself: the docked rail is always parked, and a
   *  click-pinned floating bubble does not dismiss on mouse-leave either (see
   *  onMouseLeave/hoverDriven() in photo-card.component.ts) -- only a plain
   *  hover bubble does, which is why it is excluded here. Gates the
   *  bubble's pointer-events and the person-avatar filter buttons. */
  protected readonly showInteractiveControls = computed(() => this.docked() || this.pinned());

  private readonly api = inject(ApiService);
  protected readonly store = inject(GalleryStore);
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

  private readonly rootEl = viewChild<ElementRef<HTMLElement>>('root');
  /** Measured size of the floating box; 0 until first measured. Content that
   *  arrives after the parent positioned the tooltip (image, set, faces,
   *  histogram) grows it, so the clamp must follow the real size. */
  private readonly measured = signal({ width: 0, height: 0 });
  private readonly viewport = signal({ width: window.innerWidth, height: window.innerHeight });

  /** Top edge kept inside the viewport (16px margin) once the height is known. */
  protected readonly top = computed(() => {
    const y = this.y();
    const h = this.measured().height;
    if (!h) return y;
    return Math.max(16, Math.min(y, this.viewport().height - h - 16));
  });

  /** Left edge kept inside the viewport (16px margin) once the width is known. */
  protected readonly left = computed(() => {
    const x = this.x();
    const w = this.measured().width;
    if (!w) return x;
    return Math.max(16, Math.min(x, this.viewport().width - w - 16));
  });

  constructor() {
    this.destroyRef.onDestroy(() => { this.destroyed = true; });
    const onResize = () => this.viewport.set({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener('resize', onResize);
    this.destroyRef.onDestroy(() => window.removeEventListener('resize', onResize));
    effect(onCleanup => {
      const el = this.rootEl()?.nativeElement;
      if (!el || this.docked() || typeof ResizeObserver === 'undefined') return;
      const measure = () => {
        const r = el.getBoundingClientRect();
        this.measured.set({ width: r.width, height: r.height });
        this.viewport.set({ width: window.innerWidth, height: window.innerHeight });
      };
      measure();
      const observer = new ResizeObserver(measure);
      observer.observe(el);
      onCleanup(() => observer.disconnect());
    });
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
