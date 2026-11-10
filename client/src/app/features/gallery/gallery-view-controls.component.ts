import { NgTemplateOutlet } from '@angular/common';
import { afterNextRender, ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal, TemplateRef, viewChild, viewChildren } from '@angular/core';
import { trackPendingNavigation } from '../../shared/utils/navigation-settled';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatRippleModule } from '@angular/material/core';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SortOptionIconPipe } from '../../shared/pipes/sort-option-icon.pipe';
import { SortGroupIconPipe, SortGroupKeyPipe } from '../../shared/pipes/sort-group-key.pipe';
import { useDesktopSignal, useHoverCapableSignal, DETAILS_RAIL_MIN_WIDTH_PX } from '../../shared/utils/media-query';
import { GalleryFilters, GalleryStore } from './gallery.store';
import { TILE_FITS, GalleryMode, PanelActivation, TooltipMode } from './gallery-filters.util';
import { closeOverlayDirectives } from '../../shared/utils/overlays';
import { sortLabelKey } from '../../shared/utils/sort-label';
import { AuthService } from '../../core/services/auth.service';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';

const sortOptionLabelKey = (column: string): string => `sort_options.${column}`;

/** One collection-command owner at every viewport width. */
@Component({
  selector: 'app-gallery-view-controls',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, MatBadgeModule, MatButtonModule, MatRippleModule, MatIconModule, MatMenuModule, MatTooltipModule, TranslatePipe, SortOptionIconPipe, SortGroupKeyPipe, SortGroupIconPipe],
  host: { class: 'flex flex-wrap items-center gap-1' },
  template: `
    <ng-template #displayControls>
    @if (auth.isEdition() && store.config()?.features?.show_rating_controls) {
      <label class="inline-flex min-h-11 cursor-pointer items-center gap-2 px-2 text-xs" [matTooltip]="I18N.gallery.review_navigation.help | translate">
        <input type="checkbox" data-review-advance [checked]="reviewNavigation.enabled()"
               (change)="setReviewAdvance($event)" />
        {{ I18N.gallery.review_navigation.advance | translate }}
      </label>
    }
    @if (!portDisplay()) { <ng-container [ngTemplateOutlet]="layoutControls" [ngTemplateOutletContext]="{ $implicit: secondaryLayouts }" /> }
    @if (portDisplay()) {
      <ng-container [ngTemplateOutlet]="choiceRow" [ngTemplateOutletContext]="{ id: 'tooltip-mode', icon: tooltipIcon(), label: I18N.gallery.tooltip_mode.label, value: tooltipModeLabel(), menu: tooltipModeMenu, tip: I18N.gallery.display_tips.tooltip_mode }" />
      @if (store.galleryMode() === 'grid' && store.filters().hide_details) {
        <ng-container [ngTemplateOutlet]="choiceRow" [ngTemplateOutletContext]="{ id: 'tile-fit', icon: 'aspect_ratio', label: I18N.gallery.tile_fit.label, value: tileFitLabel(), menu: tileFitMenu, tip: I18N.gallery.display_tips.tile_fit }" />
      }
    } @else {
      <button mat-button class="!min-h-11 !min-w-11 !w-11 !px-2 @[1120px]:!w-auto @[1120px]:!px-4"
              [matMenuTriggerFor]="tooltipModeMenu" [matTooltip]="I18N.gallery.tooltip_mode.label | translate"
              [attr.aria-label]="I18N.gallery.tooltip_mode.label | translate">
        <mat-icon class="!m-0 @[1120px]:!mr-2">{{ tooltipIcon() }}</mat-icon>
        <span class="hidden @[1120px]:inline">{{ I18N.gallery.tooltip_mode.label | translate }}</span>
      </button>
      @if (store.galleryMode() === 'grid' && store.filters().hide_details) {
        <button mat-button data-tile-fit class="!min-h-11 !min-w-11 !w-11 !px-2 @[1120px]:!w-auto @[1120px]:!px-4"
                [matMenuTriggerFor]="tileFitMenu" [matTooltip]="I18N.gallery.tile_fit.label | translate"
                [attr.aria-label]="I18N.gallery.tile_fit.label | translate">
          <mat-icon class="!m-0 @[1120px]:!mr-2">aspect_ratio</mat-icon>
          <span class="hidden @[1120px]:inline">{{ I18N.gallery.tile_fit.label | translate }}</span>
        </button>
      }
    }
    <ng-template #choiceRow let-id="id" let-icon="icon" let-label="label" let-value="value" let-menu="menu" let-tip="tip">
      <button type="button" matRipple [attr.data-choice]="id" aria-haspopup="menu" [matMenuTriggerFor]="menu" [matTooltip]="tip | translate"
              class="flex w-full min-h-10 items-center gap-3 rounded-md px-2 py-1 text-left hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
              [attr.aria-label]="I18N.gallery.sidebar.review.value_aria | translate:{ label: (label | translate), value: (value | translate) }">
        <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-80">{{ icon }}</mat-icon>
        <span class="flex-1 min-w-0 text-sm break-words">{{ label | translate }}</span>
        <span class="shrink-0 text-xs text-[var(--mat-sys-on-surface-variant)]" data-value>{{ value | translate }}</span>
        <mat-icon class="!text-xl !w-5 !h-5 !leading-5 shrink-0 opacity-70">expand_more</mat-icon>
      </button>
    </ng-template>
    <mat-menu #tileFitMenu="matMenu">
      @for (fit of tileFits; track fit) {
        <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().tile_fit === fit" (click)="setPresentationFilter('tile_fit', fit)">
          <mat-icon>{{ store.filters().tile_fit === fit ? 'check' : 'crop_square' }}</mat-icon>
          {{ (fit === 'square' ? I18N.gallery.tile_fit.square : I18N.gallery.tile_fit.natural) | translate }}
        </button>
      }
    </mat-menu>
    <button mat-button class="!min-h-11 !min-w-11" [class.!w-full]="portDisplay()" [class.!justify-start]="portDisplay()" (click)="toggleSlideshow()"
            [matTooltip]="I18N.slideshow.start | translate" [attr.aria-label]="I18N.slideshow.start | translate">
      <mat-icon [style.color]="store.slideshowActive() ? 'var(--mat-sys-primary)' : ''">slideshow</mat-icon>
      @if (portDisplay()) { <span>{{ I18N.slideshow.start | translate }}</span> }
    </button>
    @if (portDisplay()) {
      <button mat-button data-reset-display class="!min-h-11 !w-full !justify-start" (click)="resetDisplay()"
              [matTooltip]="I18N.gallery.display_tips.reset_display | translate" [attr.aria-label]="I18N.gallery.reset_display | translate">
        <mat-icon>restart_alt</mat-icon><span>{{ I18N.gallery.reset_display | translate }}</span>
      </button>
    }
    <mat-menu #tooltipModeMenu="matMenu">
      @for (mode of tooltipModes(); track mode.id) {
        <button mat-menu-item role="menuitemradio"
                [disabled]="mode.id === 'hover' && (!canUseHoverTooltips() || !canHoverAtAll()) && store.filters().tooltip_mode !== 'hover'"
                [attr.aria-checked]="store.filters().tooltip_mode === mode.id"
                (click)="setPresentationFilter('tooltip_mode', mode.id)">
          <mat-icon aria-hidden="true">{{ mode.icon }}</mat-icon>
          <span class="flex items-center gap-4">
            <span class="grow">{{ mode.label | translate }}</span>
            @if (store.filters().tooltip_mode === mode.id) { <mat-icon aria-hidden="true">check</mat-icon> }
          </span>
        </button>
        @if (mode.id === 'panel' && store.filters().tooltip_mode === 'panel') {
          <button mat-menu-item [matMenuTriggerFor]="panelActivationMenu">
            <mat-icon aria-hidden="true">{{ panelActivationIcon() }}</mat-icon>{{ I18N.gallery.panel_activation.label | translate }}
          </button>
        }
      }
    </mat-menu>
    <mat-menu #panelActivationMenu="matMenu">
      @for (mode of panelActivationModes; track mode.id) {
        <button mat-menu-item role="menuitemradio" [attr.aria-checked]="store.filters().panel_activation === mode.id"
                [disabled]="mode.id === 'hover' && !canHoverAtAll() && store.filters().panel_activation !== 'hover'"
                (click)="setPresentationFilter('panel_activation', mode.id)">
          <mat-icon aria-hidden="true">{{ mode.icon }}</mat-icon>
          <span class="flex items-center gap-4">
            <span class="grow">{{ mode.label | translate }}</span>
            @if (store.filters().panel_activation === mode.id) { <mat-icon aria-hidden="true">check</mat-icon> }
          </span>
        </button>
      }
    </mat-menu>
    </ng-template>
    @if (!portDisplay()) { <ng-container [ngTemplateOutlet]="displayControls" /> }
    <ng-template #primaryControls let-inPopover="inPopover">
      @if (!pinned()) {
        @let sortTooltip = I18N.gallery.sort_current | translate:{ label: (currentSortLabelKey() | translate) };
        <button mat-button data-collection-sort
                class="!min-h-11 !min-w-11 !text-[var(--mat-sys-on-surface)] @[960px]:!w-auto @[960px]:!px-2"
                [class.!w-11]="!inPopover" [class.!px-2]="!inPopover" [class.grow]="inPopover" [class.!justify-start]="inPopover"
                [matMenuTriggerFor]="sortMenu" [matTooltip]="sortTooltip" [attr.aria-label]="sortTooltip">
          @let currentIcon = store.filters().sort | sortOptionIcon;
          <mat-icon aria-hidden="true" class="text-center @[960px]:!mr-2" [class.!m-0]="!inPopover" [class.!w-8]="!inPopover" [class]="currentIcon.classes">{{ currentIcon.text }}</mat-icon>
          <span class="hidden @[960px]:inline" [class.!inline]="inPopover">{{ currentSortLabelKey() | translate }}</span>
        </button>
        <button mat-icon-button class="!h-11 !w-11 !min-w-11 !p-2.5" (click)="toggleSortDirection()"
                [matTooltip]="store.filters().sort_direction === 'DESC' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)"
                [attr.aria-label]="store.filters().sort_direction === 'DESC' ? (I18N.gallery.sort_desc | translate) : (I18N.gallery.sort_asc | translate)">
          <mat-icon>{{ store.filters().sort_direction === 'DESC' ? 'arrow_downward' : 'arrow_upward' }}</mat-icon>
        </button>
      }
    </ng-template>
    @if (!portPrimary()) { <ng-container [ngTemplateOutlet]="primaryControls" /> }
    <ng-template #filterControls>
      @if (!pinned()) {
        <button mat-button class="!min-h-11 !min-w-11 !px-2 !text-[var(--mat-sys-on-surface)]" [class.!bg-[var(--mat-sys-secondary-container)]]="store.filterDrawerOpen()" (click)="toggleFilters()"
                [matBadge]="store.activeFilterCount() || null" matBadgeColor="primary" matBadgeSize="medium"
                [matTooltip]="I18N.gallery.filters | translate"
                [attr.aria-label]="store.activeFilterCount() ? (I18N.gallery.sidebar.tabs.active_count | translate:{ label: (I18N.gallery.filters | translate), count: store.activeFilterCount() }) : (I18N.gallery.filters | translate)"
                [attr.aria-expanded]="store.filterDrawerOpen()">
          <mat-icon>filter_alt</mat-icon>
          <span>{{ I18N.gallery.filters | translate }}</span>
        </button>
      }
    </ng-template>
    @if (!portFilters()) { <ng-container [ngTemplateOutlet]="filterControls" /> }
    <ng-template #layoutControls let-choices>
      @for (layout of choices; track layout.id) {
        <button mat-button [attr.data-gallery-layout]="layout.id"
                class="!min-h-11 !min-w-11 !w-11 !px-2 @[1120px]:!w-auto @[1120px]:!px-4 !text-[var(--mat-sys-on-surface)]"
                [class.!bg-[var(--mat-sys-secondary-container)]]="store.galleryMode() === layout.id"
                [attr.aria-pressed]="store.galleryMode() === layout.id"
                [attr.aria-label]="layout.label | translate" [matTooltip]="layout.label | translate" (click)="setLayout(layout.id)">
          <mat-icon class="!m-0 @[1120px]:!mr-2">{{ layout.icon }}</mat-icon><span class="hidden @[1120px]:inline">{{ layout.label | translate }}</span>
        </button>
      }
    </ng-template>
    <ng-template #sidebarLayoutControls><ng-container [ngTemplateOutlet]="layoutControls" [ngTemplateOutletContext]="{ $implicit: layouts }" /></ng-template>
<mat-menu #sortMenu="matMenu">
    @for (section of sortMenuSections(); track section.header ?? section.options[0].column) {
      @if (section.header) {
        <button mat-menu-item data-sort-group [matMenuTriggerFor]="groupMenu"
                [class.!bg-[var(--mat-sys-primary-container)]]="section.active" [class.!text-[var(--mat-sys-on-primary-container)]]="section.active">
          <mat-icon aria-hidden="true" class="!w-8 text-center" [class.!text-[var(--mat-sys-on-primary-container)]]="section.active">{{ section.header | sortGroupIcon }}</mat-icon>
          <span class="flex items-center gap-4">
            <span class="grow">{{ ('sort_groups.' + (section.header | sortGroupKey)) | translate }}</span>
            @if (section.active) { <span class="text-xs font-medium">{{ currentSortLabelKey() | translate }}</span> }
          </span>
        </button>
        <mat-menu #groupMenu="matMenu">
          @for (opt of section.options; track opt.column) {
            @let optionIcon = opt.column | sortOptionIcon;
            @let current = store.filters().sort === opt.column;
            <button mat-menu-item role="menuitemradio" [attr.aria-checked]="current" (click)="onSortChange(opt.column)"
                    [class.!bg-[var(--mat-sys-primary-container)]]="current" [class.!text-[var(--mat-sys-on-primary-container)]]="current">
              <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="optionIcon.classes">{{ optionIcon.text }}</mat-icon>
              <span class="flex items-center gap-4">
                <span class="grow">{{ opt.labelKey | translate }}</span>
                @if (current) { <span class="flex"><mat-icon aria-hidden="true" class="!text-[var(--mat-sys-on-primary-container)]">check</mat-icon></span> }
              </span>
            </button>
          }
        </mat-menu>
      } @else {
        @for (opt of section.options; track opt.column) {
          @let optionIcon = opt.column | sortOptionIcon;
          @let current = store.filters().sort === opt.column;
          <button mat-menu-item role="menuitemradio" [attr.aria-checked]="current" (click)="onSortChange(opt.column)"
                  [class.!bg-[var(--mat-sys-primary-container)]]="current" [class.!text-[var(--mat-sys-on-primary-container)]]="current">
            <mat-icon aria-hidden="true" class="!w-8 text-center" [class]="optionIcon.classes">{{ optionIcon.text }}</mat-icon>
            <span class="flex items-center gap-4">
              <span class="grow">{{ opt.labelKey | translate }}</span>
              @if (current) { <span class="flex"><mat-icon aria-hidden="true" class="!text-[var(--mat-sys-on-primary-container)]">check</mat-icon></span> }
            </span>
          </button>
        }
      }
    }
  </mat-menu>`,
})
export class GalleryViewControlsComponent {
  readonly portDisplay = input(false);
  readonly slideshowRequested = output<void>();
  readonly displayControls = viewChild<TemplateRef<unknown>>('displayControls');
  readonly portPrimary = input(false);
  readonly portFilters = input(false);
  readonly filterControls = viewChild<TemplateRef<unknown>>('filterControls');
  readonly primaryControls = viewChild<TemplateRef<unknown>>('primaryControls');
  readonly layoutControls = viewChild<TemplateRef<unknown>>('layoutControls');
  readonly sidebarLayoutControls = viewChild<TemplateRef<unknown>>('sidebarLayoutControls');
  protected readonly layouts = [
    { id: 'grid', icon: 'grid_view', label: I18N.gallery.layout_grid },
    { id: 'mosaic', icon: 'auto_awesome_mosaic', label: I18N.gallery.layout_mosaic },
    { id: 'list', icon: 'view_list', label: I18N.gallery.layout_list },
  ] as const;
  readonly primaryLayouts = this.layouts.slice(0, 2);
  protected readonly secondaryLayouts = this.layouts.slice(2);

  protected readonly I18N = i18nKeys();
  protected readonly store = inject(GalleryStore);
  protected readonly pinned = computed(() => this.store.pinnedPaths() !== null);
  private readonly controlsActive = signal(true);
  private readonly navigationPending = trackPendingNavigation({ started: () => this.closeOverlays() });
  private readonly canAct = computed(() => this.controlsActive() && !this.navigationPending());
  private readonly menus = viewChildren(MatMenuTrigger);
  private readonly tooltips = viewChildren(MatTooltip);
  private readonly railCapable = useDesktopSignal({ breakpointPx: DETAILS_RAIL_MIN_WIDTH_PX });
  /** Below the desktop breakpoint the floating hover bubble never renders. */
  private readonly tooltipCapable = useDesktopSignal();
  /** Hover is equally meaningless on a pure touch device at any width: the tap's
   *  synthetic mouseenter fires once and sticks, so the gallery suppresses it. */
  private readonly hoverCapable = useHoverCapableSignal();
  protected readonly canDockDetails = this.railCapable.isDesktop;
  protected readonly canUseHoverTooltips = this.tooltipCapable.isDesktop;
  protected readonly canHoverAtAll = this.hoverCapable.isHoverCapable;
  protected readonly tooltipModes = computed(() => {
    const modes: { id: TooltipMode; label: string; icon: string }[] = [
      { id: 'hover', label: I18N.gallery.tooltip_mode.hover, icon: 'chat_bubble_outline' },
      { id: 'click', label: I18N.gallery.tooltip_mode.click, icon: 'touch_app' },
      { id: 'panel', label: I18N.gallery.tooltip_mode.panel, icon: 'view_sidebar' },
      { id: 'off', label: I18N.gallery.tooltip_mode.off, icon: 'visibility_off' },
    ];
    return modes.filter(mode => mode.id !== 'panel' || this.canDockDetails());
  });
  private readonly tooltipModeIcons: Record<TooltipMode, string> = { hover: 'chat_bubble_outline', click: 'touch_app', panel: 'view_sidebar', off: 'visibility_off' };
  protected readonly tooltipIcon = computed(() => this.tooltipModeIcons[this.store.filters().tooltip_mode] ?? 'chat_bubble_outline');
  private readonly tooltipModeLabels: Record<TooltipMode, string> = {
    hover: I18N.gallery.tooltip_mode.hover, click: I18N.gallery.tooltip_mode.click, panel: I18N.gallery.tooltip_mode.panel, off: I18N.gallery.tooltip_mode.off,
  };
  protected readonly tooltipModeLabel = computed(() => this.tooltipModeLabels[this.store.filters().tooltip_mode] ?? I18N.gallery.tooltip_mode.off);
  protected readonly tileFitLabel = computed(() => this.store.filters().tile_fit === 'natural' ? I18N.gallery.tile_fit.natural : I18N.gallery.tile_fit.square);
  protected readonly panelActivationModes: { id: PanelActivation; label: string; icon: string }[] = [
    { id: 'hover', label: I18N.gallery.panel_activation.hover, icon: 'chat_bubble_outline' },
    { id: 'click', label: I18N.gallery.panel_activation.click, icon: 'touch_app' },
    { id: 'both', label: I18N.gallery.panel_activation.both, icon: 'swap_horiz' },
  ];
  protected readonly panelActivationIcon = computed(() =>
    this.panelActivationModes.find(mode => mode.id === this.store.filters().panel_activation)?.icon ?? 'swap_horiz');
  protected resetDisplay(): void {
    if (this.canAct()) void this.store.resetDisplay();
  }
  protected setLayout(mode: GalleryMode): void {
    if (this.canAct()) this.store.setGalleryMode(mode);
  }
  protected readonly auth = inject(AuthService);
  protected readonly reviewNavigation = inject(GalleryReviewNavigationService);
  protected readonly tileFits = TILE_FITS;
  protected setReviewAdvance(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (this.canAct()) this.reviewNavigation.setEnabled(input.checked);
    input.checked = this.reviewNavigation.enabled();
  }
  constructor() {
    afterNextRender(() => { this.railCapable.setup(); this.tooltipCapable.setup(); this.hoverCapable.setup(); });
    inject(DestroyRef).onDestroy(() => { this.railCapable.cleanup(); this.tooltipCapable.cleanup(); this.hoverCapable.cleanup(); });

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
    if (!this.canAct()) return;
    this.slideshowRequested.emit();
    this.store.slideshowActive.update(active => !active);
  }
  protected readonly sortGroups = computed(() => {
    const grouped = this.store.config()?.sort_options_grouped;
    if (!grouped) return null;
    return Object.entries(grouped);
  });

  protected readonly sortMenuSections = computed(() => {
    const filters = this.store.filters();
    const sections: { header: string | null; active: boolean; options: { column: string; labelKey: string }[] }[] = [];
    if (filters.semanticQuery) sections.push({ header: null, active: false, options: [{ column: 'relevance', labelKey: I18N.gallery.sort_relevance }] });
    if (this.store.config()?.features?.show_my_taste) sections.push({ header: null, active: false, options: [{ column: 'learned_score', labelKey: I18N.gallery.sort_my_taste }] });
    const groups = this.sortGroups();
    if (groups) {
      for (const [name, options] of groups) {
        sections.push({
          header: name, active: options.some(opt => opt.column === filters.sort),
          options: options.map(opt => ({ column: opt.column, labelKey: sortOptionLabelKey(opt.column) })),
        });
      }
    } else {
      sections.push({ header: null, active: false, options: [
        { column: 'aggregate', labelKey: I18N.gallery.sort_aggregate },
        { column: 'aesthetic', labelKey: I18N.gallery.sort_aesthetic },
        { column: 'date_taken', labelKey: I18N.gallery.sort_date },
      ] });
    }
    return sections;
  });

  protected readonly currentSortLabelKey = computed(() => {
    const sort = this.store.filters().sort;
    const match = this.sortMenuSections().flatMap(section => section.options).find(opt => opt.column === sort);
    return match?.labelKey ?? sortLabelKey(sort);
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
