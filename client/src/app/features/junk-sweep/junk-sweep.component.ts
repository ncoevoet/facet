import { Component, inject, signal, OnInit, HostListener } from '@angular/core';
import { NgClass } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { JunkKindLabelPipe } from './junk-sweep.pipes';
import { I18N } from '../../core/i18n/keys';

interface JunkPhoto {
  path: string;
  filename: string;
  junk_kind: string | null;
  aggregate: number | null;
}

interface PhotosResponse {
  photos: JunkPhoto[];
  total: number;
  total_pages: number;
  page: number;
  has_more: boolean;
}

const ANY_KIND = 'any';

@Component({
  selector: 'app-junk-sweep',
  host: { class: 'block h-full overflow-y-auto' },
  imports: [
    NgClass,
    MatIconModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    ImageUrlPipe,
    LoupeDirective,
    JunkKindLabelPipe,
  ],
  template: `
    <div class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%]">
      <div class="flex items-center gap-3 mb-1">
        <h2 class="text-lg font-semibold">{{ I18N.junk.title | translate }}</h2>
        <span class="text-xs text-white/40">{{ I18N.junk.count | translate:{ count: total() } }}</span>
        <div class="flex items-center gap-2 ml-auto">
          @if (photos().length > 0) {
            <button mat-flat-button color="warn" (click)="rejectAllShown()">
              <mat-icon>delete_sweep</mat-icon>
              {{ I18N.junk.reject_all | translate }}
            </button>
          }
          <button mat-stroked-button (click)="loupeActive.set(!loupeActive())"
                  [class.!border-[var(--mat-sys-primary)]]="loupeActive()"
                  [matTooltip]="I18N.scenes.loupe_hint | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
          </button>
          @if (loupeActive()) {
            <mat-slider class="!w-28 !min-w-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.scenes.loupe | translate" />
            </mat-slider>
          }
        </div>
      </div>
      <p class="text-sm text-white/50 mb-4">{{ I18N.junk.subtitle | translate }}</p>

      <div class="flex flex-wrap items-center gap-2 mb-4">
        <button mat-stroked-button (click)="selectKind(ANY_KIND)"
                [ngClass]="activeKind() === ANY_KIND ? '!border-[var(--mat-sys-primary)] !text-[var(--mat-sys-primary)]' : ''">
          {{ I18N.junk.all_kinds | translate }}
        </button>
        @for (k of kinds(); track k[0]) {
          <button mat-stroked-button (click)="selectKind(k[0])"
                  [ngClass]="activeKind() === k[0] ? '!border-[var(--mat-sys-primary)] !text-[var(--mat-sys-primary)]' : ''">
            {{ k[0] | junkKindLabel }}
            <span class="text-xs text-white/40 ml-1">{{ k[1] }}</span>
          </button>
        }
      </div>

      @if (loading() && photos().length === 0) {
        <div class="flex justify-center py-10"><mat-spinner diameter="32" /></div>
      } @else if (photos().length === 0) {
        <div class="text-white/50 py-10 text-center whitespace-pre-line">{{ I18N.junk.empty | translate }}</div>
      } @else {
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          @for (photo of photos(); track photo.path) {
            <div class="group relative w-full aspect-[4/3] rounded-xl overflow-hidden border-2 border-white/20">
              <img [src]="photo.path | thumbnailUrl:320"
                   [appLoupe]="photo.path | imageUrl:true"
                   [loupeActive]="loupeActive()"
                   [loupeZoom]="loupeZoom()"
                   class="w-full h-full object-cover"
                   [alt]="photo.filename" loading="lazy" />
              <span class="absolute top-1 left-1 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded">
                {{ photo.junk_kind | junkKindLabel }}
              </span>
              <div class="absolute inset-x-0 bottom-0 flex justify-between gap-1 p-1.5 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                <button mat-flat-button class="!min-w-0 !px-2 !text-xs" (click)="keep(photo)"
                        [matTooltip]="I18N.junk.keep_hint | translate">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">check</mat-icon>
                  {{ I18N.junk.keep | translate }}
                </button>
                <button mat-flat-button color="warn" class="!min-w-0 !px-2 !text-xs" (click)="reject(photo)"
                        [matTooltip]="I18N.junk.reject_hint | translate">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4">delete</mat-icon>
                  {{ I18N.junk.reject | translate }}
                </button>
              </div>
            </div>
          }
        </div>
        @if (hasMore()) {
          <div class="flex justify-center py-4">
            <button mat-stroked-button (click)="loadMore()" [disabled]="loading()">{{ I18N.junk.load_more | translate }}</button>
          </div>
        }
      }
    </div>
  `,
})
export class JunkSweepComponent implements OnInit {
  protected readonly I18N = I18N;
  protected readonly ANY_KIND = ANY_KIND;
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);

  protected readonly photos = signal<JunkPhoto[]>([]);
  protected readonly kinds = signal<[string, number][]>([]);
  protected readonly activeKind = signal<string>(ANY_KIND);
  protected readonly loading = signal(true);
  protected readonly total = signal(0);
  protected readonly hasMore = signal(false);

  private readonly loupe = createLoupeState();
  protected readonly loupeActive = this.loupe.loupeActive;
  protected readonly loupeZoom = this.loupe.loupeZoom;

  private page = 1;
  private readonly perPage = 48;
  private loadGeneration = 0;

  async ngOnInit(): Promise<void> {
    void this.loadKinds();
    await this.load();
  }

  private async loadKinds(): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.api.get<{ junk_kinds: [string, number][] }>('/filter_options/junk_kinds'),
      );
      this.kinds.set(data.junk_kinds ?? []);
    } catch {
      // Chips stay empty; the "All kinds" view still works.
    }
  }

  @HostListener('document:keydown.z', ['$event'])
  protected onZoomToggle(event: Event): void {
    this.loupe.toggle(event);
  }

  protected async selectKind(kind: string): Promise<void> {
    if (kind === this.activeKind()) return;
    this.activeKind.set(kind);
    this.page = 1;
    this.photos.set([]);
    await this.load();
  }

  private async load(): Promise<void> {
    const gen = ++this.loadGeneration;
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<PhotosResponse>('/photos', {
          junk_kind: this.activeKind(),
          page: this.page,
          per_page: this.perPage,
          hide_rejected: 1,
          hide_blinks: 0,
          hide_bursts: 0,
          hide_duplicates: 0,
        }),
      );
      if (gen !== this.loadGeneration) return;
      this.photos.update(list => [...list, ...data.photos]);
      this.total.set(data.total);
      this.hasMore.set(this.page < data.total_pages);
    } catch {
      if (gen !== this.loadGeneration) return;
      this.snack.open(this.i18n.t(I18N.junk.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    } finally {
      if (gen === this.loadGeneration) this.loading.set(false);
    }
  }

  protected async loadMore(): Promise<void> {
    if (!this.hasMore() || this.loading()) return;
    this.page++;
    await this.load();
  }

  /** Keep a candidate: clear its junk label so it leaves the queue permanently. */
  protected async keep(photo: JunkPhoto): Promise<void> {
    this.removeLocal(photo);
    try {
      await firstValueFrom(this.api.post('/photo/clear_junk', { photo_path: photo.path }));
      this.snack.open(this.i18n.t(I18N.junk.kept), this.i18n.t(I18N.common.dismiss), { duration: 1500 });
    } catch {
      this.restoreLocal(photo);
      this.snack.open(this.i18n.t(I18N.junk.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    }
  }

  /** Reject a candidate via the shared batch_reject plumbing (single path). */
  protected async reject(photo: JunkPhoto): Promise<void> {
    this.removeLocal(photo);
    try {
      await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: [photo.path] }));
      this.snack.open(this.i18n.t(I18N.junk.rejected), this.i18n.t(I18N.common.dismiss), { duration: 1500 });
    } catch {
      this.restoreLocal(photo);
      this.snack.open(this.i18n.t(I18N.junk.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    }
  }

  protected async rejectAllShown(): Promise<void> {
    const shown = this.photos();
    if (shown.length === 0) return;
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.junk.confirm_reject_all_title),
        message: this.i18n.t(I18N.junk.confirm_reject_all_message, { count: shown.length }),
      },
    });
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;

    const paths = shown.map(p => p.path);
    try {
      await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: paths }));
      this.snack.open(
        this.i18n.t(I18N.junk.rejected_bulk, { count: paths.length }),
        this.i18n.t(I18N.common.dismiss), { duration: 2000 });
      const removedByKind = new Map<string, number>();
      for (const p of shown) {
        if (p.junk_kind) removedByKind.set(p.junk_kind, (removedByKind.get(p.junk_kind) ?? 0) + 1);
      }
      this.kinds.update(list =>
        list.map(k => [k[0], Math.max(0, k[1] - (removedByKind.get(k[0]) ?? 0))] as [string, number]));
      this.page = 1;
      this.photos.set([]);
      await this.load();
    } catch {
      this.snack.open(this.i18n.t(I18N.junk.load_error), this.i18n.t(I18N.common.dismiss), { duration: 3000 });
    }
  }

  private removeLocal(photo: JunkPhoto): void {
    this.photos.update(list => list.filter(p => p.path !== photo.path));
    this.total.update(t => Math.max(0, t - 1));
    if (photo.junk_kind) {
      this.kinds.update(list =>
        list.map(k => (k[0] === photo.junk_kind ? [k[0], Math.max(0, k[1] - 1)] as [string, number] : k)));
    }
  }

  private restoreLocal(photo: JunkPhoto): void {
    this.photos.update(list => [photo, ...list]);
    this.total.update(t => t + 1);
    if (photo.junk_kind) {
      this.kinds.update(list =>
        list.map(k => (k[0] === photo.junk_kind ? [k[0], k[1] + 1] as [string, number] : k)));
    }
  }
}
