import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, signal, viewChild, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationCancel, NavigationCancellationCode, NavigationEnd, NavigationError, NavigationSkipped, NavigationStart, Router } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltip, MatTooltipModule } from '@angular/material/tooltip';
import { GalleryStore, GalleryFilters } from './gallery.store';
import { PersonFilterChipComponent } from './person-filter-chip.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { I18N, i18nKeys } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { folderDisplayName } from '../folders/folders.util';
import { isUnavailableKey, unavailableSet } from '../../shared/utils/unavailable-metrics';
import { CaptureDatePipe } from '../../shared/pipes/capture-date.pipe';
import { GalleryAlbumRulesComponent } from './gallery-album-rules.component';

@Component({selector:'app-gallery-criteria', changeDetection:ChangeDetectionStrategy.OnPush,
 imports:[MatIconModule, MatSliderModule, MatTooltipModule, PersonFilterChipComponent, TranslatePipe, ThumbnailUrlPipe, GalleryAlbumRulesComponent],
 host:{class:'block'}, template:`
 @if (store.currentAlbum()) { <app-gallery-album-rules [active]="canAct()" /> }
 @if (pinned()) {
   <p data-criteria-pinned class="text-xs my-2 text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.criteria.pinned | translate }}</p>
 } @else {
 <div class="flex items-center flex-wrap gap-x-3 gap-y-1 mt-2 text-xs text-[var(--mat-sys-on-surface-variant)]">
   <details #quickFilters tabindex="-1" class="relative" (keydown.escape)="quickFilters.open = false; quickSummary.focus(); $event.preventDefault(); $event.stopPropagation()">
     <summary #quickSummary class="cursor-pointer py-2 font-medium">{{ I18N.gallery.sidebar.review.quick | translate }}</summary>
     <div class="absolute top-full left-0 z-30 min-w-56 max-w-[80vw] rounded-md border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface)] p-2 shadow-lg flex flex-wrap gap-1">
       <p class="m-0 basis-full p-1 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.criteria.quick_help | translate }}</p>
       <button type="button" class="px-3 py-2 rounded hover:bg-[var(--mat-sys-surface-container)]" [class.bg-[var(--mat-sys-secondary-container)]]="store.filters().favorites_only" [attr.aria-pressed]="store.filters().favorites_only" (click)="quickFilter('favorites')">{{ I18N.gallery.favorites_only | translate }}</button>
       @for (status of statuses; track status.id) {
         <button type="button" class="px-3 py-2 rounded hover:bg-[var(--mat-sys-surface-container)]" [class.bg-[var(--mat-sys-secondary-container)]]="store.filters().review_status === status.id" [attr.aria-pressed]="store.filters().review_status === status.id" (click)="quickFilter(status.id)">{{ status.label | translate }}</button>
       }
     </div>
   </details>
   @if (visibilityRules().length) {
     <details #visibility tabindex="-1" class="min-w-0" (keydown.escape)="visibility.open = false; visibilitySummary.focus(); $event.preventDefault(); $event.stopPropagation()">
       <summary #visibilitySummary data-visibility-summary class="cursor-pointer py-2">{{ I18N.gallery.criteria.visibility | translate:{ count: visibilityRules().length } }}</summary>
       <div class="flex flex-wrap gap-2 pb-2">
         @for (rule of visibilityRules(); track rule.id) {
           <button type="button" class="inline-flex items-center gap-1 rounded border border-[var(--mat-sys-outline-variant)] px-2 py-1.5" [attr.aria-label]="I18N.gallery.criteria.remove | translate:{ label: (rule.labelKey | translate) }" (click)="clearFilterChip(rule)">{{ rule.labelKey | translate }}: {{ rule.valueKey | translate }}<mat-icon class="!text-sm !w-4 !h-4" aria-hidden="true">close</mat-icon></button>
         }
       </div>
     </details>
   }
   @if (store.filters().semanticQuery || store.filters().similar_to) {
     <span data-query-kind [matTooltip]="I18N.gallery.criteria.ranked_help | translate">{{ I18N.gallery.criteria.ranked | translate }}</span>
   } @else if (activeFilterChips().length) {
     <span data-query-kind>{{ I18N.gallery.criteria.exact | translate }}</span>
   }
 </div>
 @if (store.filters().semanticQuery || store.filters().similar_to) {
   <p data-query-explanation class="m-0 text-xs text-[var(--mat-sys-on-surface-variant)]">{{ I18N.gallery.criteria.ranked_help | translate }}</p>
 }
 @if (activeFilterChips().length || store.filters().similar_to) {
    <div data-active-criteria role="group" [attr.aria-label]="I18N.gallery.criteria.label | translate" class="flex items-center gap-2 flex-wrap py-2">
      @if (store.filters().similar_to) {
        <div class="inline-flex flex-wrap max-w-full items-center gap-1.5 pl-1 pr-1 py-0.5 rounded-md bg-[var(--mat-sys-secondary-container)] text-[var(--mat-sys-on-secondary-container)] text-xs font-medium">
          <img [src]="store.filters().similar_to | thumbnailUrl:48"
               class="w-7 h-7 rounded-full object-cover shrink-0"
               alt="" />
          <!-- Mode toggle buttons -->
          <div class="inline-flex items-center rounded-full overflow-hidden border border-[var(--mat-sys-outline-variant)]">
            @for (m of SIMILARITY_MODES; track m.id) {
              <button
                class="inline-flex items-center justify-center w-9 h-9 max-sm:w-11 max-sm:h-11 transition-colors"
                [class.bg-[var(--mat-sys-primary)]]="store.filters().similarity_mode === m.id"
                [class.text-[var(--mat-sys-on-primary)]]="store.filters().similarity_mode === m.id"
                [class.hover:bg-black/10]="store.filters().similarity_mode !== m.id"
                [matTooltip]="'similar.mode_' + m.id | translate"
                [attr.aria-label]="'similar.mode_' + m.id | translate"
                [attr.aria-pressed]="store.filters().similarity_mode === m.id"
                (click)="onSimilarityModeChange(m.id)"
              >
                <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">{{ m.icon }}</mat-icon>
              </button>
            }
          </div>
          @if (store.filters().similarity_mode !== 'person') {
            <mat-slider class="!w-24 !min-w-0" [min]="0" [max]="90" [step]="5" [discrete]="true">
              <input matSliderThumb
                     [attr.aria-label]="I18N.gallery.criteria.similarity | translate"
                     [value]="similaritySliderValue()"
                     (valueChange)="onSimilarityFilterChange($event)" />
            </mat-slider>
            <span class="font-medium w-8 text-right shrink-0">{{ similaritySliderValue() }}%</span>
          }
          <button
            class="inline-flex items-center justify-center min-w-8 min-h-8 max-sm:min-w-11 max-sm:min-h-11 rounded-full hover:bg-black/20 transition-colors"
            (click)="clearSimilarFilter()"
            [attr.aria-label]="I18N.gallery.criteria.remove | translate:{ label: (I18N.gallery.criteria.ranked | translate) }"
          >
            <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">close</mat-icon>
          </button>
        </div>
      }
      @for (chip of activeFilterChips(); track chip.id) {
        @if (chip.personId) {
          @if (canAct()) {
            <app-person-filter-chip [personId]="chip.personId" [canEdit]="auth.isEdition()" (remove)="clearFilterChip(chip)" />
          } @else {
            <span class="px-2 py-1 text-xs">{{ chip.labelKey | translate }}: {{ chip.value }}</span>
          }
        } @else {
          <div class="inline-flex items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full bg-[var(--mat-sys-secondary-container)] text-[var(--mat-sys-on-secondary-container)] text-xs font-medium">
            <span class="opacity-70">{{ chip.labelKey | translate }}</span>
            @if (chip.value) {
              <span class="mx-0.5 max-w-64 truncate" [title]="chip.value">{{ chip.value }}</span>
            }
            <button
              class="inline-flex items-center justify-center min-w-8 min-h-8 max-sm:min-w-11 max-sm:min-h-11 rounded-full hover:bg-black/20 transition-colors"
              (click)="clearFilterChip(chip)"
              [attr.aria-label]="I18N.gallery.criteria.remove | translate:{ label: (chip.labelKey | translate) }"
            >
              <mat-icon class="!text-sm !w-3.5 !h-3.5 !leading-[14px]">close</mat-icon>
            </button>
          </div>
        }
      }
      @if (activeFilterChips().length > 1) {
        <button class="text-xs opacity-60 hover:opacity-100 transition-opacity ml-auto shrink-0" (click)="resetFilters()">
          {{ I18N.gallery.reset_filters | translate }}
        </button>
      }
    </div>
  }
 }`})
export class GalleryCriteriaComponent {
 protected readonly I18N=i18nKeys();
 protected readonly store=inject(GalleryStore);
 protected readonly auth=inject(AuthService);
 private readonly i18n=inject(I18nService);
 private readonly router=inject(Router);
 protected readonly pinned=computed(()=>this.store.pinnedPaths()!==null);
 private readonly active=signal(true);
 private readonly pending=signal(false);
 protected readonly canAct=computed(()=>this.active()&&!this.pending()&&!this.pinned());
 private readonly date = new CaptureDatePipe();
 private readonly tooltips = viewChildren(MatTooltip);
 private readonly quickDetails = viewChild<ElementRef<HTMLDetailsElement>>('quickFilters');
 private readonly visibilityDetails = viewChild<ElementRef<HTMLDetailsElement>>('visibility');
 protected readonly statuses = [
   { id: 'undecided', label: I18N.gallery.sidebar.review.values.undecided },
   { id: 'kept', label: I18N.review.kept },
   { id: 'rejected', label: I18N.review.rejected },
 ] as const;
 protected quickFilter(value: 'favorites' | 'undecided' | 'kept' | 'rejected'): void {
   if (!this.canAct()) return;
   if (value === 'favorites') void this.store.updateFilter('favorites_only', !this.store.filters().favorites_only);
   else void this.store.updateFilter('review_status', this.store.filters().review_status === value ? '' : value);
 }
 protected readonly visibilityRules = computed(() => {
   const f = this.store.filters();
   const labels = I18N.gallery.sidebar.review;
   const rules: { id: string; labelKey: string; valueKey: string; clearKeys: string[] }[] = [];
   if (!f.blinks_only && !f.duplicates_only && !f.show_rejected) {
     for (const [key, labelKey, valueKey] of [
       ['hide_blinks', labels.blinks, labels.values.hidden],
       ['hide_bursts', labels.bursts, labels.values.best_frame],
       ['hide_duplicates', labels.duplicates, labels.values.best_frame],
       ['hide_brackets', labels.brackets, labels.values.base_exposure],
       ['hide_panoramas', labels.panoramas, labels.values.middle_frame],
     ] as const) if (f[key]) rules.push({ id: key, labelKey, valueKey, clearKeys: [key] });
   }
   if (f.hide_rejected && !f.review_status && !f.show_rejected) rules.push({ id: 'hide_rejected', labelKey: labels.rejected, valueKey: labels.values.hidden, clearKeys: ['hide_rejected'] });
   return rules;
 });
 constructor(){
  this.router.events.pipe(takeUntilDestroyed()).subscribe(event=>{
   if(event instanceof NavigationStart){this.pending.set(true);this.closeDisclosures();}
   else if(event instanceof NavigationCancel){
    if(event.code!==NavigationCancellationCode.Redirect&&event.code!==NavigationCancellationCode.SupersededByNewNavigation)this.pending.set(false);
   }else if(event instanceof NavigationEnd||event instanceof NavigationError||event instanceof NavigationSkipped)this.pending.set(false);
  });
 }
 setActive(active:boolean):void { this.active.set(active); if(!active)this.closeDisclosures(); }
 private closeDisclosures():void {
   for(const details of [this.quickDetails(),this.visibilityDetails()])if(details)details.nativeElement.open=false;
   for(const tooltip of this.tooltips())tooltip.hide(0);
 }
 protected resetFilters():void {if(this.canAct())void this.store.resetFilters();}
 protected onSimilarityFilterChange(value:number):void {if(this.canAct())void this.store.updateFilter('min_similarity',String(value));}
 protected clearSimilarFilter():void {if(this.canAct())void this.store.updateFilters({similar_to:'',similarity_mode:'visual',min_similarity:'70'});}
 protected onSimilarityModeChange(mode:'visual'|'color'|'person'):void {if(this.canAct())void this.store.updateFilter('similarity_mode',mode);}
 protected clearFilterChip(chip:{id:string;clearKeys:string[]}):void {
  if(!this.canAct())return;
  if(chip.clearKeys.includes('album_id')){void this.router.navigate(['/']);return;}
  const person=chip.clearKeys.find(key=>key.startsWith('person_'));
  if(person){
   // Keep the store's last-person-cleared option refresh, not just its photo reload.
   void this.store.updateFilter('person_id',this.store.filters().person_id.split(',').filter(id=>id!==person.slice(7)).join(','));
   return;
  }
  const updates:Partial<GalleryFilters>={};
  for(const key of chip.clearKeys){
   const typed=key as keyof GalleryFilters;
   Object.assign(updates,{[typed]:typeof this.store.filters()[typed]==='boolean'?false:''});
  }
  void this.store.updateFilters(updates);
 }
 private static readonly RANGE_CHIPS: { minKey: string; maxKey: string; labelKey: string }[] = [
    { minKey: 'min_score', maxKey: 'max_score', labelKey: 'gallery.score_range' },
    { minKey: 'min_aesthetic', maxKey: 'max_aesthetic', labelKey: 'gallery.aesthetic_range' },
    { minKey: 'min_quality_score', maxKey: 'max_quality_score', labelKey: 'gallery.quality_score_range' },
    { minKey: 'min_topiq', maxKey: 'max_topiq', labelKey: 'gallery.topiq_range' },
    { minKey: 'min_face_quality', maxKey: 'max_face_quality', labelKey: 'gallery.face_quality_range' },
    { minKey: 'min_eye_sharpness', maxKey: 'max_eye_sharpness', labelKey: 'gallery.eye_sharpness_range' },
    { minKey: 'min_face_sharpness', maxKey: 'max_face_sharpness', labelKey: 'gallery.face_sharpness_range' },
    { minKey: 'min_face_ratio', maxKey: 'max_face_ratio', labelKey: 'gallery.face_ratio_range' },
    { minKey: 'min_face_count', maxKey: 'max_face_count', labelKey: 'gallery.face_count_range' },
    { minKey: 'min_face_confidence', maxKey: 'max_face_confidence', labelKey: 'gallery.face_confidence_range' },
    { minKey: 'min_composition', maxKey: 'max_composition', labelKey: 'gallery.composition_range' },
    { minKey: 'min_sharpness', maxKey: 'max_sharpness', labelKey: 'gallery.sharpness_range' },
    { minKey: 'min_exposure', maxKey: 'max_exposure', labelKey: 'gallery.exposure_range' },
    { minKey: 'min_color', maxKey: 'max_color', labelKey: 'gallery.color_range' },
    { minKey: 'min_contrast', maxKey: 'max_contrast', labelKey: 'gallery.contrast_range' },
    { minKey: 'min_noise', maxKey: 'max_noise', labelKey: 'gallery.noise_range' },
    { minKey: 'min_dynamic_range', maxKey: 'max_dynamic_range', labelKey: 'gallery.dynamic_range' },
    { minKey: 'min_saturation', maxKey: 'max_saturation', labelKey: 'gallery.saturation_range' },
    { minKey: 'min_luminance', maxKey: 'max_luminance', labelKey: 'gallery.luminance_range' },
    { minKey: 'min_histogram_spread', maxKey: 'max_histogram_spread', labelKey: 'gallery.histogram_range' },
    { minKey: 'min_power_point', maxKey: 'max_power_point', labelKey: 'gallery.power_point_range' },
    { minKey: 'min_leading_lines', maxKey: 'max_leading_lines', labelKey: 'gallery.leading_lines_range' },
    { minKey: 'min_isolation', maxKey: 'max_isolation', labelKey: 'gallery.isolation_range' },
    { minKey: 'min_aesthetic_iaa', maxKey: 'max_aesthetic_iaa', labelKey: 'gallery.aesthetic_iaa_range' },
    { minKey: 'min_face_quality_iqa', maxKey: 'max_face_quality_iqa', labelKey: 'gallery.face_quality_iqa_range' },
    { minKey: 'min_liqe', maxKey: 'max_liqe', labelKey: 'gallery.liqe_range' },
    { minKey: 'min_qrealign', maxKey: 'max_qrealign', labelKey: 'gallery.qrealign_range' },
    { minKey: 'min_aesthetic_v25', maxKey: 'max_aesthetic_v25', labelKey: 'gallery.aesthetic_v25_range' },
    { minKey: 'min_deqa', maxKey: 'max_deqa', labelKey: 'gallery.deqa_range' },
    { minKey: 'min_subject_sharpness', maxKey: 'max_subject_sharpness', labelKey: 'gallery.subject_sharpness_range' },
    { minKey: 'min_subject_prominence', maxKey: 'max_subject_prominence', labelKey: 'gallery.subject_prominence_range' },
    { minKey: 'min_subject_placement', maxKey: 'max_subject_placement', labelKey: 'gallery.subject_placement_range' },
    { minKey: 'min_bg_separation', maxKey: 'max_bg_separation', labelKey: 'gallery.bg_separation_range' },
    { minKey: 'min_moment_confidence', maxKey: 'max_moment_confidence', labelKey: 'gallery.moment_confidence_range' },
    { minKey: 'min_star_rating', maxKey: 'max_star_rating', labelKey: 'gallery.star_rating_range' },
    { minKey: 'min_iso', maxKey: 'max_iso', labelKey: 'gallery.iso_range' },
    { minKey: 'min_aperture', maxKey: 'max_aperture', labelKey: 'gallery.aperture_range' },
    { minKey: 'min_focal_length', maxKey: 'max_focal_length', labelKey: 'gallery.focal_range' },
    { minKey: 'date_from', maxKey: 'date_to', labelKey: 'gallery.sidebar.date' },
    { minKey: 'min_channel_clip_shadow', maxKey: 'max_channel_clip_shadow', labelKey: 'gallery.channel_clip_shadow_range' },
    { minKey: 'min_channel_clip_highlight', maxKey: 'max_channel_clip_highlight', labelKey: 'gallery.channel_clip_highlight_range' },
  ];

protected readonly activeFilterChips = computed<{ id: string; labelKey: string; value: string; clearKeys: string[]; personId?: number }[]>(() => {
    if (this.pinned()) return [];
    const f = this.store.filters();
    this.i18n.translations();  // re-run on language change so translated chip values stay current
    const chips: { id: string; labelKey: string; value: string; clearKeys: string[]; personId?: number }[] = [];

    // Album filter
    if (f.album_id) {
      const album = this.store.currentAlbum();
      const name = album?.name || `#${f.album_id}`;
      chips.push({ id: 'album', labelKey: 'nav.albums', value: name, clearKeys: ['album_id'] });
    }

    // Semantic search
    if (f.semanticQuery) chips.push({ id: 'semanticQuery', labelKey: 'gallery.semantic_search_chip', value: f.semanticQuery, clearKeys: ['semanticQuery'] });
    if (f.semanticQuery && f.search_threshold) chips.push({ id: 'search_threshold', labelKey: I18N.gallery.semantic_search_threshold, value: `${f.search_threshold}%`, clearKeys: ['search_threshold'] });
    if (f.type) chips.push({ id: 'type', labelKey: I18N.ui.filters.type, value: this.i18n.t(f.type === 'top_picks' ? 'photo_types.top_picks' : 'category_names.' + f.type), clearKeys: ['type'] });
    if (f.review_status) chips.push({ id: 'review_status', labelKey: I18N.gallery.sidebar.review.decision, value: this.i18n.t('gallery.sidebar.review.values.' + f.review_status), clearKeys: ['review_status'] });
    if (f.sequence_override) chips.push({ id: 'sequence_override', labelKey: I18N.gallery.sequence_override.label, value: this.i18n.t('gallery.sequence_override.' + f.sequence_override), clearKeys: ['sequence_override'] });
    if (f.no_gps) chips.push({ id: 'no_gps', labelKey: I18N.gallery.sidebar.location, value: this.i18n.t(I18N.gallery.criteria.no_location), clearKeys: ['no_gps'] });

    // Simple string/select filters
    if (f.tag) chips.push({ id: 'tag', labelKey: 'gallery.tag', value: f.tag, clearKeys: ['tag'] });
    if (f.search) chips.push({ id: 'search', labelKey: 'gallery.search_chip', value: f.search, clearKeys: ['search'] });
    if (f.camera) chips.push({ id: 'camera', labelKey: 'gallery.camera', value: f.camera, clearKeys: ['camera'] });
    if (f.lens) chips.push({ id: 'lens', labelKey: 'gallery.lens', value: f.lens, clearKeys: ['lens'] });
    if (f.composition_pattern) chips.push({ id: 'composition_pattern', labelKey: 'gallery.composition_pattern', value: f.composition_pattern, clearKeys: ['composition_pattern'] });
    if (f.quality_tier) chips.push({ id: 'quality_tier', labelKey: 'gallery.quality_tier', value: this.i18n.t('gallery.quality_tiers.' + f.quality_tier), clearKeys: ['quality_tier'] });
    if (f.color_temp) chips.push({ id: 'color_temp', labelKey: 'gallery.color_temp', value: this.i18n.t('gallery.color_temps.' + f.color_temp), clearKeys: ['color_temp'] });
    if (f.hue_bucket) chips.push({ id: 'hue_bucket', labelKey: 'gallery.hue', value: this.i18n.t('gallery.hue_buckets.' + f.hue_bucket), clearKeys: ['hue_bucket'] });
    if (f.path_prefix) chips.push({ id: 'path_prefix', labelKey: 'folders.title', value: folderDisplayName(f.path_prefix), clearKeys: ['path_prefix'] });

    // Person filter — one chip per selected person
    if (f.person_id) {
      const ids = f.person_id.split(',').filter(Boolean);
      for (const pid of ids) {
        const person = this.store.persons().find(p => String(p.id) === pid);
        const name = person?.name || `#${pid}`;
        chips.push({ id: `person_${pid}`, labelKey: 'gallery.person', value: name, clearKeys: [`person_${pid}`], personId: Number(pid) });
      }
    }

    // GPS location filter
    if (f.gps_lat && f.gps_lng) {
      const locationName = this.store.gpsLocationName() || `${(+f.gps_lat).toFixed(2)}, ${(+f.gps_lng).toFixed(2)}`;
      const radius = f.gps_radius_km ? ` — ${f.gps_radius_km} km` : '';
      chips.push({ id: 'gps', labelKey: 'gallery.sidebar.location', value: locationName + radius, clearKeys: ['gps_lat', 'gps_lng', 'gps_radius_km'] });
    }

    // Boolean filters
    if (f.favorites_only) chips.push({ id: 'favorites_only', labelKey: 'gallery.favorites_only', value: '', clearKeys: ['favorites_only'] });
    if (f.is_monochrome) chips.push({ id: 'is_monochrome', labelKey: 'gallery.monochrome_only', value: '', clearKeys: ['is_monochrome'] });
    if (f.manual_faces_need_review) chips.push({ id: 'manual_faces_need_review', labelKey: I18N.gallery.manual_faces_need_review, value: '', clearKeys: ['manual_faces_need_review'] });
    for (const [key, labelKey] of [
      ['show_rejected', I18N.gallery.sidebar.review.values.only_rejected],
      ['blinks_only', I18N.gallery.sidebar.review.desc.blinks_only],
      ['duplicates_only', I18N.gallery.sidebar.review.desc.duplicates_only],
      ['faces_need_names', I18N.gallery.faces_need_names],
    ] as const) if (f[key]) chips.push({ id: key, labelKey, value: '', clearKeys: [key] });

    // Range/date filter pairs (metrics hidden by the licensing policy get no chip)
    const hiddenMetrics = unavailableSet(this.store.config()?.unavailable_metrics);
    for (const { minKey, maxKey, labelKey } of GalleryCriteriaComponent.RANGE_CHIPS) {
      if (isUnavailableKey(minKey, hiddenMetrics)) continue;
      const rawMin = (f as unknown as Record<string, string>)[minKey];
      const rawMax = (f as unknown as Record<string, string>)[maxKey];
      const min = minKey === 'date_from' ? this.date.transform(rawMin) : rawMin;
      const max = maxKey === 'date_to' ? this.date.transform(rawMax) : rawMax;
      if (min || max) {
        const value = (min && max) ? `${min}–${max}` : min ? `≥${min}` : `≤${max}`;
        chips.push({ id: minKey, labelKey, value, clearKeys: [minKey, maxKey] });
      }
    }

    return chips;
  });

protected readonly SIMILARITY_MODES = [
    { id: 'visual', icon: 'image_search' },
    { id: 'color', icon: 'palette' },
    { id: 'person', icon: 'person_search' },
  ] as const;

protected readonly similaritySliderValue = computed(() => parseInt(this.store.filters().min_similarity || '70', 10));
}
