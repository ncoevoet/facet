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
import { MatBadgeModule } from '@angular/material/badge';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { AuthService } from './core/services/auth.service';
import { I18nService } from './core/services/i18n.service';
import { GalleryStore } from './features/gallery/gallery.store';
import type { GalleryFilters } from './features/gallery/gallery.store';
import { TranslatePipe } from './shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from './shared/pipes/thumbnail-url.pipe';

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
  ],
  templateUrl: './app.html',
  host: { class: 'block h-full' },
})
export class App implements OnInit {
  private router = inject(Router);
  private dialog = inject(MatDialog);
  auth = inject(AuthService);
  i18n = inject(I18nService);
  store = inject(GalleryStore);
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

  readonly activeFilterChips = computed(() => {
    const f = this.store.filters();
    const chips: { label: string; action: () => void }[] = [];

    // Type
    if (f.type) {
      const typeObj = this.store.types().find(t => t.id === f.type);
      chips.push({ label: typeObj?.label ?? f.type, action: () => this.store.updateFilter('type', '') });
    }

    // Camera
    if (f.camera) {
      chips.push({ label: `${this.i18n.t('gallery.camera')}: ${f.camera}`, action: () => this.store.updateFilter('camera', '') });
    }

    // Lens
    if (f.lens) {
      chips.push({ label: `${this.i18n.t('gallery.lens')}: ${f.lens}`, action: () => this.store.updateFilter('lens', '') });
    }

    // Tag
    if (f.tag) {
      chips.push({ label: `${this.i18n.t('gallery.tag')}: ${f.tag}`, action: () => this.store.updateFilter('tag', '') });
    }

    // Person
    if (f.person_id) {
      const ids = new Set(f.person_id.split(','));
      const names = this.store.persons()
        .filter(p => ids.has(String(p.id)))
        .map(p => p.name ?? this.i18n.t('gallery.unknown_person'))
        .join(', ');
      chips.push({ label: `${this.i18n.t('gallery.person')}: ${names || f.person_id}`, action: () => this.store.updateFilter('person_id', '') });
    }

    // Search
    if (f.search) {
      chips.push({ label: `"${f.search}"`, action: () => this.store.updateFilter('search', '') });
    }

    // Composition pattern
    if (f.composition_pattern) {
      const patternLabel = this.i18n.t(`composition_patterns.${f.composition_pattern}`);
      chips.push({ label: `${this.i18n.t('gallery.composition_pattern')}: ${patternLabel}`, action: () => this.store.updateFilter('composition_pattern', '') });
    }

    // Aperture
    if (f.aperture) {
      chips.push({ label: `f/${f.aperture}`, action: () => this.store.updateFilter('aperture', '') });
    }

    // Focal length
    if (f.focal_length) {
      chips.push({ label: `${f.focal_length}mm`, action: () => this.store.updateFilter('focal_length', '') });
    }

    // Boolean filters
    if (f.favorites_only) {
      chips.push({ label: this.i18n.t('gallery.favorites_only'), action: () => this.store.updateFilter('favorites_only', false) });
    }
    if (f.is_monochrome) {
      chips.push({ label: this.i18n.t('gallery.monochrome_only'), action: () => this.store.updateFilter('is_monochrome', false) });
    }

    // Range pairs
    const rangePairs: Array<{ label: string; minKey: keyof GalleryFilters; maxKey: keyof GalleryFilters }> = [
      { label: this.i18n.t('gallery.score_range'), minKey: 'min_score', maxKey: 'max_score' },
      { label: this.i18n.t('gallery.aesthetic_range'), minKey: 'min_aesthetic', maxKey: 'max_aesthetic' },
      { label: this.i18n.t('gallery.face_quality_range'), minKey: 'min_face_quality', maxKey: 'max_face_quality' },
      { label: this.i18n.t('gallery.composition_range'), minKey: 'min_composition', maxKey: 'max_composition' },
      { label: this.i18n.t('gallery.sharpness_range'), minKey: 'min_sharpness', maxKey: 'max_sharpness' },
      { label: this.i18n.t('gallery.exposure_range'), minKey: 'min_exposure', maxKey: 'max_exposure' },
      { label: this.i18n.t('gallery.color_range'), minKey: 'min_color', maxKey: 'max_color' },
      { label: this.i18n.t('gallery.contrast_range'), minKey: 'min_contrast', maxKey: 'max_contrast' },
      { label: this.i18n.t('gallery.noise_range'), minKey: 'min_noise', maxKey: 'max_noise' },
      { label: this.i18n.t('gallery.dynamic_range'), minKey: 'min_dynamic_range', maxKey: 'max_dynamic_range' },
      { label: this.i18n.t('gallery.face_count_range'), minKey: 'min_face_count', maxKey: 'max_face_count' },
      { label: this.i18n.t('gallery.eye_sharpness_range'), minKey: 'min_eye_sharpness', maxKey: 'max_eye_sharpness' },
      { label: this.i18n.t('gallery.face_sharpness_range'), minKey: 'min_face_sharpness', maxKey: 'max_face_sharpness' },
      { label: this.i18n.t('gallery.iso_range'), minKey: 'min_iso', maxKey: 'max_iso' },
    ];

    for (const { label, minKey, maxKey } of rangePairs) {
      const min = f[minKey] as string;
      const max = f[maxKey] as string;
      if (min || max) {
        const rangeStr = min && max ? `${min}–${max}` : min ? `≥${min}` : `≤${max}`;
        chips.push({
          label: `${label}: ${rangeStr}`,
          action: () => this.store.updateFilters({ [minKey]: '', [maxKey]: '' } as Partial<GalleryFilters>),
        });
      }
    }

    // Date range
    if (f.date_from || f.date_to) {
      let dateLabel: string;
      if (f.date_from && f.date_to) {
        dateLabel = `${f.date_from} → ${f.date_to}`;
      } else if (f.date_from) {
        dateLabel = `${this.i18n.t('gallery.date_from')}: ${f.date_from}`;
      } else {
        dateLabel = `${this.i18n.t('gallery.date_to')}: ${f.date_to}`;
      }
      chips.push({ label: dateLabel, action: () => this.store.updateFilters({ date_from: '', date_to: '' }) });
    }

    return chips;
  });

  async ngOnInit(): Promise<void> {
    await this.i18n.load();
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
