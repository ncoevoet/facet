import { NgTemplateOutlet } from '@angular/common';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, signal, TemplateRef, viewChild, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SortOptionIconPipe } from '../../shared/pipes/sort-option-icon.pipe';
import { SortGroupKeyPipe } from '../../shared/pipes/sort-group-key.pipe';
import { useDesktopSignal, DETAILS_RAIL_MIN_WIDTH_PX } from '../../shared/utils/media-query';
import { GalleryFilters, GalleryStore } from './gallery.store';
import { closeOverlayDirectives } from '../../shared/utils/overlays';
import { GalleryDisplayPreset, galleryPresentation } from './gallery-presentation.util';
import { AuthService } from '../../core/services/auth.service';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';

const sortOptionLabelKey = (column: string): string => `sort_options.${column}`;

/** One collection-command owner at every viewport width. */
@Component({
  selector: 'app-gallery-view-controls',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, MatBadgeModule, MatButtonModule, MatIconModule, MatMenuModule, MatTooltipModule, TranslatePipe, SortOptionIconPipe, SortGroupKeyPipe],
  host: { class: 'flex flex-wrap items-center gap-1' },
  template: `
    @if (auth.isEdition() && store.config()?.features?.show_rating_controls) {
      <label class="inline-flex min-h-11 cursor-pointer items-center gap-2 px-2 text-xs" [matTooltip]="I18N.gallery.review_navigation.help | translate">
        <input type="checkbox" data-review-advance [checked]="reviewNavigation.enabled()"
               (change)="setReviewAdvance($event)" />
        {{ I18N.gallery.review_navigation.advance | translate }}
      </label>
    }
    <button mat-button data-display-presets class="max-md:!min-w-11 max-md:!w-11 max-md:!px-2" [matMenuTriggerFor]="displayPresetMenu"
            [attr.aria-label]="I18N.gallery.presentation.label | translate"
            [matTooltip]="I18N.gallery.presentation.help | translate">
      <mat-icon class="max-md:!m-0">tune</mat-icon><span class="hidden md:inline">{{ I18N.gallery.presentation.label | translate }}</span>
    </button>
    <mat-menu #displayPresetMenu="matMenu">
      <p class="m-0 px-4 py-2 max-w-72 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.presentation.help | translate }}</p>
      @for (preset of presets; track preset.id) {
        <button mat-menu-item role="menuitemradio" [attr.aria-checked]="activePreset() === preset.id"
                [attr.data-display-preset]="preset.id" (click)="applyPreset(preset.id)">
          <mat-icon>{{ activePreset() === preset.id ? 'check' : preset.icon }}</mat-icon>{{ preset.label | translate }}
        </button>
      }
      <button mat-menu-item data-reset-display (click)="applyPreset('default')"><mat-icon>restart_alt</mat-icon>{{ I18N.gallery.presentation.reset | translate }}</button>
    </mat-menu>
    <ng-template #primaryControls>
    @if (!pinned()) {
          @let sortTooltip = I18N.gallery.sort_current | translate:{ label: (currentSortLabelKey() | translate) };
          <button mat-button data-collection-sort class="max-md:!min-h-11 max-md:!min-w-11 max-md:!w-11 max-md:!px-2" [matMenuTriggerFor]="sortMenu" [matTooltip]="sortTooltip" [attr.aria-label]="sortTooltip">
            @let currentIcon = store.filters().sort | sortOptionIcon;
            <mat-icon aria-hidden="true" class="!w-8 -mx-1 text-center max-md:!m-0" [class]="currentIcon.classes">{{ currentIcon.text }}</mat-icon>
          <span class="hidden @[1120px]:inline">{{ currentSortLabelKey() | translate }}</span></button>
          <button
            class="max-md:!min-h-11 max-md:!min-w-11"
            mat-icon-button
            (click)="toggleSortDirection()"
            [matTooltip]="store.filters().sort_direction === 'DESC' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
            [attr.aria-label]="store.filters().sort_direction === 'DESC' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
          >
            <mat-icon>{{
              store.filters().sort_direction === 'DESC' ? 'arrow_downward' : 'arrow_upward'
            }}</mat-icon>
          </button>
          <button
            class="max-md:!min-h-11 max-md:!px-2"
            mat-button
            (click)="toggleFilters()"
            [matBadge]="store.activeFilterCount() || null"
            matBadgeColor="primary"
            matBadgeSize="small"
            [matTooltip]="I18N.gallery.filters | translate"
            [attr.aria-label]="I18N.gallery.filters | translate"
           [attr.aria-expanded]="store.filterDrawerOpen()">
            <mat-icon [style.color]="store.filterDrawerOpen() ? 'var(--mat-sys-primary)' : ''">filter_alt</mat-icon>
          <span>{{ I18N.gallery.filters | translate }}</span></button>
        }
    </ng-template>
    @if (!portPrimary()) { <ng-container [ngTemplateOutlet]="primaryControls" /> }

<button
          class="max-md:!min-w-11 max-md:!w-11 max-md:!px-2"
          mat-button
          [matMenuTriggerFor]="tooltipModeMenu"
          [matTooltip]="I18N.gallery.tooltip_mode.label | translate"
          [attr.aria-label]="I18N.gallery.tooltip_mode.label | translate"
        >
          <mat-icon class="max-md:!m-0">{{
            store.filters().tooltip_mode === 'click' ? 'touch_app'
            : store.filters().tooltip_mode === 'off' ? 'visibility_off'
            : store.filters().tooltip_mode === 'panel' ? 'view_sidebar'
            : 'chat_bubble_outline'
          }}</mat-icon>
        <span class="hidden @[1120px]:inline">{{ I18N.gallery.tooltip_mode.label | translate }}</span></button>
<button
          class=""
          mat-icon-button
          (click)="toggleSlideshow()"
          [matTooltip]="I18N.slideshow.start | translate"
          [attr.aria-label]="I18N.slideshow.start | translate"
        >
          <mat-icon [style.color]="store.slideshowActive() ? 'var(--mat-sys-primary)' : ''">slideshow</mat-icon>
        </button>
<mat-menu #tooltipModeMenu="matMenu">
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().tooltip_mode === 'hover'" (click)="setPresentationFilter('tooltip_mode', 'hover')">
      <mat-icon aria-hidden="true">chat_bubble_outline</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.tooltip_mode.hover | translate }}</span>
        @if (store.filters().tooltip_mode === 'hover') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().tooltip_mode === 'click'" (click)="setPresentationFilter('tooltip_mode', 'click')">
      <mat-icon aria-hidden="true">touch_app</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.tooltip_mode.click | translate }}</span>
        @if (store.filters().tooltip_mode === 'click') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
    @if (canDockDetails()) {
      <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().tooltip_mode === 'panel'" (click)="setPresentationFilter('tooltip_mode', 'panel')">
        <mat-icon aria-hidden="true">view_sidebar</mat-icon>
        <span class="flex items-center gap-4">
          <span class="grow">{{ I18N.gallery.tooltip_mode.panel | translate }}</span>
          @if (store.filters().tooltip_mode === 'panel') {
            <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
          }
        </span>
      </button>
      @if (store.filters().tooltip_mode === 'panel') {
        <button mat-menu-item [matMenuTriggerFor]="panelActivationMenu">
          <mat-icon aria-hidden="true">{{
            store.filters().panel_activation === 'hover' ? 'chat_bubble_outline'
            : store.filters().panel_activation === 'click' ? 'touch_app'
            : 'swap_horiz'
          }}</mat-icon>
          {{ I18N.gallery.panel_activation.label | translate }}
        </button>
      }
    }
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().tooltip_mode === 'off'" (click)="setPresentationFilter('tooltip_mode', 'off')">
      <mat-icon aria-hidden="true">visibility_off</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.tooltip_mode.off | translate }}</span>
        @if (store.filters().tooltip_mode === 'off') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
  </mat-menu>
<mat-menu #panelActivationMenu="matMenu">
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().panel_activation === 'hover'" (click)="setPresentationFilter('panel_activation', 'hover')">
      <mat-icon aria-hidden="true">chat_bubble_outline</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.panel_activation.hover | translate }}</span>
        @if (store.filters().panel_activation === 'hover') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().panel_activation === 'click'" (click)="setPresentationFilter('panel_activation', 'click')">
      <mat-icon aria-hidden="true">touch_app</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.panel_activation.click | translate }}</span>
        @if (store.filters().panel_activation === 'click') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
    <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().panel_activation === 'both'" (click)="setPresentationFilter('panel_activation', 'both')">
      <mat-icon aria-hidden="true">swap_horiz</mat-icon>
      <span class="flex items-center gap-4">
        <span class="grow">{{ I18N.gallery.panel_activation.both | translate }}</span>
        @if (store.filters().panel_activation === 'both') {
          <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
        }
      </span>
    </button>
  </mat-menu>
<mat-menu #sortMenu="matMenu">
    @for (section of sortMenuSections(); track section.header ?? section.options[0].column) {
      @let headerId = 'sort-menu-group-' + $index;
      <div [attr.role]="section.header ? 'group' : 'none'" [attr.aria-labelledby]="section.header ? headerId : null">
        @if (section.header) {
          <div [id]="headerId" class="px-4 pt-2 pb-1 text-xs font-medium uppercase opacity-70">{{ ('sort_groups.' + (section.header | sortGroupKey)) | translate }}</div>
        }
        @for (opt of section.options; track opt.column) {
          @let optionIcon = opt.column | sortOptionIcon;
          <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().sort === opt.column" (click)="onSortChange(opt.column)">
            <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="optionIcon.classes">{{ optionIcon.text }}</mat-icon>
            <span class="flex items-center gap-4">
              <span class="grow">{{ opt.labelKey | translate }}</span>
              @if (store.filters().sort === opt.column) {
                <span class="flex"><mat-icon aria-hidden="true">check</mat-icon></span>
              }
            </span>
          </button>
        }
      </div>
    }
  </mat-menu>`,
})
export class GalleryViewControlsComponent {
  readonly portPrimary = input(false);
  readonly primaryControls = viewChild<TemplateRef<unknown>>('primaryControls');

  protected readonly I18N = i18nKeys();
  protected readonly store = inject(GalleryStore);
  protected readonly pinned = computed(() => this.store.pinnedPaths() !== null);
  private readonly controlsActive = signal(true);
  private readonly navigationPending = signal(false);
  private readonly canAct = computed(() => this.controlsActive() && !this.navigationPending());
  private readonly router = inject(Router);
  private readonly menus = viewChildren(MatMenuTrigger);
  private readonly tooltips = viewChildren(MatTooltip);
  private readonly railCapable = useDesktopSignal({ breakpointPx: DETAILS_RAIL_MIN_WIDTH_PX });
  protected readonly canDockDetails = this.railCapable.isDesktop;
  protected readonly presets: { id: GalleryDisplayPreset; label: string; icon: string }[] = [
    { id: 'browse', label: I18N.gallery.presentation.browse, icon: 'photo_library' },
    { id: 'review', label: I18N.gallery.presentation.review, icon: 'fact_check' },
    { id: 'organize', label: I18N.gallery.presentation.organize, icon: 'folder' },
  ];
  protected readonly activePreset = computed(() => {
    const filters = this.store.filters();
    return this.presets.find(({ id }) => {
      const candidate = galleryPresentation(id, this.canDockDetails());
      return candidate.mode === this.store.galleryMode() && candidate.cardWidth === this.store.cardWidth()
        && candidate.hide_details === filters.hide_details && candidate.tooltip_mode === filters.tooltip_mode
        && candidate.panel_activation === filters.panel_activation;
    })?.id ?? null;
  });

  protected applyPreset(preset: GalleryDisplayPreset | 'default'): void {
    if (this.canAct()) void this.store.applyDisplayPreset(preset, this.canDockDetails());
  }
  protected readonly auth = inject(AuthService);
  protected readonly reviewNavigation = inject(GalleryReviewNavigationService);
  protected setReviewAdvance(event: Event): void {
    if (this.canAct()) this.reviewNavigation.setEnabled((event.target as HTMLInputElement).checked);
  }
  constructor() {
    afterNextRender(() => this.railCapable.setup());
    inject(DestroyRef).onDestroy(() => this.railCapable.cleanup());
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.navigationPending.set(true);
        this.closeOverlays();
      } else if (event instanceof NavigationCancel) {
        if (event.code !== NavigationCancellationCode.Redirect && event.code !== NavigationCancellationCode.SupersededByNewNavigation) {
          this.navigationPending.set(false);
        }
      } else if (event instanceof NavigationEnd || event instanceof NavigationError || event instanceof NavigationSkipped) {
        this.navigationPending.set(false);
      }
    });
  }

  setActive(active: boolean): void {
    this.controlsActive.set(active);
    if (!active) this.closeOverlays();
  }

  closeOverlays(): void {
    closeOverlayDirectives(this.tooltips(), this.menus());
  }

  protected setPresentationFilter<K extends keyof GalleryFilters>(key: K, value: GalleryFilters[K]): void {
    if (this.canAct()) void this.store.updateFilter(key, value);
  }

  protected toggleFilters(): void {
    if (this.canAct() && !this.pinned()) this.store.setFilterDrawerOpen(!this.store.filterDrawerOpen());
  }

  protected toggleSlideshow(): void {
    if (this.canAct()) this.store.slideshowActive.update(active => !active);
  }
  protected readonly sortGroups = computed(() => {
    const grouped = this.store.config()?.sort_options_grouped;
    if (!grouped) return null;
    return Object.entries(grouped);
  });

  protected readonly sortMenuSections = computed(() => {
    const filters = this.store.filters();
    const sections: { header: string | null; options: { column: string; labelKey: string }[] }[] = [];
    if (filters.semanticQuery) sections.push({ header: null, options: [{ column: 'relevance', labelKey: I18N.gallery.sort_relevance }] });
    if (this.store.config()?.features?.show_my_taste) sections.push({ header: null, options: [{ column: 'learned_score', labelKey: I18N.gallery.sort_my_taste }] });
    const groups = this.sortGroups();
    if (groups) {
      for (const [name, options] of groups) {
        sections.push({
          header: name,
          options: options.map(opt => ({ column: opt.column, labelKey: sortOptionLabelKey(opt.column) })),
        });
      }
    } else {
      sections.push({ header: null, options: [
        { column: 'aggregate', labelKey: I18N.gallery.sort_aggregate },
        { column: 'aesthetic', labelKey: I18N.gallery.sort_aesthetic },
        { column: 'date_taken', labelKey: I18N.gallery.sort_date },
      ] });
    }
    return sections;
  });

  private static readonly SORT_LABELS_OUTSIDE_MENU: Record<string, string> = {
    relevance: I18N.gallery.sort_relevance,
    learned_score: I18N.gallery.sort_my_taste,
    top_picks_score: I18N.photo_types.top_picks,
  };

  protected readonly currentSortLabelKey = computed(() => {
    const sort = this.store.filters().sort;
    const match = this.sortMenuSections().flatMap(section => section.options).find(opt => opt.column === sort);
    const outsideLabel = Object.hasOwn(GalleryViewControlsComponent.SORT_LABELS_OUTSIDE_MENU, sort)
      ? GalleryViewControlsComponent.SORT_LABELS_OUTSIDE_MENU[sort] : undefined;
    return match?.labelKey ?? outsideLabel ?? sortOptionLabelKey(sort);
  });

  protected onSortChange(sort: string): void {
    if (!this.canAct() || this.pinned() || sort === this.store.filters().sort) return;
    void this.store.setUserSort(sort);
  }

  protected toggleSortDirection(): void {
    if (!this.canAct() || this.pinned()) return;
    const current = this.store.filters().sort_direction;
    this.store.updateFilter('sort_direction', current === 'DESC' ? 'ASC' : 'DESC');
  }
}
