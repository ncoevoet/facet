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
import { StatsFiltersService } from './features/stats/stats-filters.service';
import { CompareFiltersService } from './features/comparison/compare-filters.service';
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
