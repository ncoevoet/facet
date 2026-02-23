import { Component, inject, computed, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterOutlet, RouterLink, RouterLinkActive, NavigationEnd } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatListModule } from '@angular/material/list';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatSliderModule } from '@angular/material/slider';
import { MatBadgeModule } from '@angular/material/badge';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { AuthService } from './core/services/auth.service';
import { I18nService } from './core/services/i18n.service';
import { ThemeService } from './core/services/theme.service';
import { GalleryStore, GalleryFilters } from './features/gallery/gallery.store';
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
import { TranslatePipe } from './shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe, ThumbnailUrlPipe } from './shared/pipes/thumbnail-url.pipe';

/** Inline dialog for edition password prompt. */
@Component({
  selector: 'app-edition-dialog',
  imports: [FormsModule, MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule, MatDialogModule, TranslatePipe],
  template: `
    <h2 mat-dialog-title class="flex items-center gap-2">
      <mat-icon>lock_open</mat-icon>
      {{ 'edition.unlock_title' | translate }}
    </h2>
    <mat-dialog-content>
      <p class="text-sm opacity-70 mb-3">{{ 'edition.unlock_description' | translate }}</p>
      <mat-form-field class="w-full">
        <mat-label>{{ 'edition.password_placeholder' | translate }}</mat-label>
        <input matInput type="password" [(ngModel)]="password" (keyup.enter)="submit()" autofocus />
      </mat-form-field>
      @if (error()) {
        <p class="text-red-400 text-sm">{{ 'edition.invalid_password' | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ 'dialog.cancel' | translate }}</button>
      <button mat-flat-button [disabled]="!password" (click)="submit()">{{ 'edition.unlock_button' | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class EditionDialogComponent {
  private dialogRef = inject(MatDialogRef<EditionDialogComponent>);
  private auth = inject(AuthService);
  password = '';
  error = signal(false);

  async submit(): Promise<void> {
    this.error.set(false);
    const ok = await this.auth.editionLogin(this.password);
    if (ok) {
      this.dialogRef.close(true);
    } else {
      this.error.set(true);
    }
  }
}

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatSidenavModule,
    MatIconModule,
    MatButtonModule,
    MatListModule,
    MatMenuModule,
    MatSelectModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatInputModule,
    MatChipsModule,
    MatBadgeModule,
    MatDividerModule,
    TranslatePipe,
    PersonThumbnailUrlPipe,
    ThumbnailUrlPipe,
    MatSliderModule,
  ],
  templateUrl: './app.html',
  host: { class: 'block h-full' },
})
export class App implements OnInit {
  private router = inject(Router);
  private dialog = inject(MatDialog);
  auth = inject(AuthService);
  i18n = inject(I18nService);
  themeService = inject(ThemeService);
  store = inject(GalleryStore);
  statsFilters = inject(StatsFiltersService);
  compareFilters = inject(CompareFiltersService);
  mobileSearchOpen = signal(false);

  private url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map(e => e.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  isGalleryRoute = computed(() => {
    const path = this.url().split('?')[0];
    return path === '/' || path === '';
  });

  isStatsRoute = computed(() => this.url().split('?')[0] === '/stats');

  isCompareRoute = computed(() => this.url().split('?')[0] === '/compare');

  sortGroups = computed(() => {
    const grouped = this.store.config()?.sort_options_grouped;
    if (!grouped) return null;
    return Object.entries(grouped);
  });

  selectedPersonIds = computed(() => {
    const raw = this.store.filters().person_id;
    return raw ? raw.split(',') : [];
  });

  selectedPersons = computed(() => {
    const ids = new Set(this.selectedPersonIds());
    if (!ids.size) return [];
    return this.store.persons().filter(p => ids.has(String(p.id)));
  });

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
    { minKey: 'min_star_rating', maxKey: 'max_star_rating', labelKey: 'gallery.star_rating_range' },
    { minKey: 'min_iso', maxKey: 'max_iso', labelKey: 'gallery.iso_range' },
    { minKey: 'min_aperture', maxKey: 'max_aperture', labelKey: 'gallery.aperture_range' },
    { minKey: 'min_focal_length', maxKey: 'max_focal_length', labelKey: 'gallery.focal_range' },
    { minKey: 'date_from', maxKey: 'date_to', labelKey: 'gallery.sidebar.date' },
  ];

  activeFilterChips = computed<{ id: string; labelKey: string; value: string; clearKeys: string[] }[]>(() => {
    if (!this.isGalleryRoute()) return [];
    const f = this.store.filters();
    const chips: { id: string; labelKey: string; value: string; clearKeys: string[] }[] = [];

    // Simple string/select filters
    if (f.tag) chips.push({ id: 'tag', labelKey: 'gallery.tag', value: f.tag, clearKeys: ['tag'] });
    if (f.search) chips.push({ id: 'search', labelKey: 'gallery.search_placeholder', value: f.search, clearKeys: ['search'] });
    if (f.camera) chips.push({ id: 'camera', labelKey: 'gallery.camera', value: f.camera, clearKeys: ['camera'] });
    if (f.lens) chips.push({ id: 'lens', labelKey: 'gallery.lens', value: f.lens, clearKeys: ['lens'] });
    if (f.composition_pattern) chips.push({ id: 'composition_pattern', labelKey: 'gallery.composition_pattern', value: f.composition_pattern, clearKeys: ['composition_pattern'] });

    // Person filter — one chip per selected person
    if (f.person_id) {
      const ids = f.person_id.split(',').filter(Boolean);
      for (const pid of ids) {
        const person = this.store.persons().find(p => String(p.id) === pid);
        const name = person?.name || `#${pid}`;
        chips.push({ id: `person_${pid}`, labelKey: 'gallery.person', value: name, clearKeys: [`person_${pid}`] });
      }
    }

    // Boolean filters
    if (f.favorites_only) chips.push({ id: 'favorites_only', labelKey: 'gallery.favorites_only', value: '', clearKeys: ['favorites_only'] });
    if (f.is_monochrome) chips.push({ id: 'is_monochrome', labelKey: 'gallery.monochrome_only', value: '', clearKeys: ['is_monochrome'] });

    // Range/date filter pairs
    for (const { minKey, maxKey, labelKey } of App.RANGE_CHIPS) {
      const min = (f as unknown as Record<string, string>)[minKey];
      const max = (f as unknown as Record<string, string>)[maxKey];
      if (min || max) {
        const value = (min && max) ? `${min}–${max}` : min ? `≥${min}` : `≤${max}`;
        chips.push({ id: minKey, labelKey, value, clearKeys: [minKey, maxKey] });
      }
    }

    return chips;
  });

  protected readonly similaritySliderValue = computed(() => parseInt(this.store.filters().min_similarity || '70', 10));

  protected onSimilarityFilterChange(value: number): void {
    this.store.updateFilter('min_similarity', String(value));
  }

  protected clearSimilarFilter(): void {
    this.store.updateFilters({ similar_to: '', min_similarity: '70' });
  }

  clearFilterChip(chip: { id: string; clearKeys: string[] }): void {
    for (const key of chip.clearKeys) {
      // Handle person_id chip removal (key = "person_N")
      if (key.startsWith('person_')) {
        const pid = key.slice('person_'.length);
        const current = this.store.filters().person_id;
        const ids = current.split(',').filter(id => id !== pid);
        this.store.updateFilter('person_id', ids.join(','));
        continue;
      }
      if (key === 'favorites_only' || key === 'is_monochrome') {
        this.store.updateFilter(key as 'favorites_only' | 'is_monochrome', false);
      } else {
        this.store.updateFilter(key as keyof GalleryFilters, '' as never);
      }
    }
  }


  async ngOnInit(): Promise<void> {
    await this.i18n.load();
    this.store.loadTypeCounts();
    try {
      await this.auth.checkStatus();
    } catch {
      // Auth check failed — guard will redirect if needed
    }
  }

  onTypeChange(type: string): void {
    this.store.updateFilter('type', type);
  }

  onSortChange(sort: string): void {
    this.store.updateFilter('sort', sort);
  }

  toggleSortDirection(): void {
    const current = this.store.filters().sort_direction;
    this.store.updateFilter('sort_direction', current === 'DESC' ? 'ASC' : 'DESC');
  }

  onSearchChange(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (value !== this.store.filters().search) {
      this.store.updateFilter('search', value);
    }
  }

  clearSearch(): void {
    this.store.updateFilter('search', '');
  }

  onStatsCategoryChange(cat: string): void {
    this.statsFilters.filterCategory.set(cat);
  }

  onCompareCategoryChange(cat: string): void {
    this.compareFilters.selectedCategory.set(cat);
  }

  onStatsDateChange(field: 'from' | 'to', event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (field === 'from') this.statsFilters.dateFrom.set(value);
    else this.statsFilters.dateTo.set(value);
  }

  onPersonChange(ids: string[]): void {
    this.store.updateFilter('person_id', ids.join(','));
  }

  switchLang(lang: string): void {
    this.i18n.setLocale(lang);
  }

  logout(): void {
    this.auth.logout();
  }

  navigateTo(path: string): void {
    this.router.navigate([path]);
  }

  showEditionDialog(): void {
    this.dialog.open(EditionDialogComponent, { width: '95vw', maxWidth: '360px' });
  }

  lockEdition(): void {
    // Drop edition privileges by logging out
    this.auth.logout();
  }
}
