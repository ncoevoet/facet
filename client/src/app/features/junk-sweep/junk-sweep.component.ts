import { Component, inject, signal, effect, viewChild, TemplateRef, OnInit, OnDestroy, HostListener } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageHelpService } from '../../core/services/page-help.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe, ImageUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { LoupeDirective } from '../../shared/directives/loupe.directive';
import { createLoupeState } from '../../shared/utils/loupe-state';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { JunkKindLabelPipe, JunkKindIconPipe } from './junk-sweep.pipes';
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
    NgTemplateOutlet,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatProgressSpinnerModule,
    MatSliderModule,
    MatTooltipModule,
    TranslatePipe,
    ThumbnailUrlPipe,
    ImageUrlPipe,
    LoupeDirective,
    JunkKindLabelPipe,
    JunkKindIconPipe,
  ],
  template: `
    <!-- The toolbar projects into the global header on lg+ (HeaderSlotService) and
         renders as a fixed bottom bar on small screens (same #junkToolbar template):
         filter group on the left, action group (loupe + reject-all) on the right. -->
    <div class="lg:hidden">
      <ng-container [ngTemplateOutlet]="junkToolbar" />
    </div>
    <ng-template #junkToolbar>
      <div class="flex items-center gap-2 md:gap-3
                  max-lg:fixed max-lg:bottom-0 max-lg:left-0 max-lg:right-0 max-lg:z-40
                  max-lg:flex-nowrap max-lg:overflow-x-auto max-lg:px-3 max-lg:py-2
                  max-lg:bg-[var(--mat-sys-surface-container)] max-lg:border-t max-lg:border-[var(--mat-sys-outline-variant)]
                  max-lg:shadow-lg">
        <button mat-icon-button [matMenuTriggerFor]="kindMenu"
                [class.!text-[var(--mat-sys-primary)]]="activeKind() !== ANY_KIND"
                [matTooltip]="activeKind() === ANY_KIND ? (I18N.junk.all_kinds | translate) : (activeKind() | junkKindLabel)"
                [attr.aria-label]="activeKind() === ANY_KIND ? (I18N.junk.all_kinds | translate) : (activeKind() | junkKindLabel)">
          <mat-icon>{{ activeKind() | junkKindIcon }}</mat-icon>
        </button>
        <mat-menu #kindMenu="matMenu">
          <button mat-menu-item (click)="selectKind(ANY_KIND)">
            <mat-icon>{{ ANY_KIND | junkKindIcon }}</mat-icon>
            <span [class.font-bold]="activeKind() === ANY_KIND">{{ I18N.junk.all_kinds | translate }}</span>
          </button>
          @for (k of kinds(); track k[0]) {
            <button mat-menu-item (click)="selectKind(k[0])">
              <mat-icon>{{ k[0] | junkKindIcon }}</mat-icon>
              <span [class.font-bold]="activeKind() === k[0]">{{ k[0] | junkKindLabel }}</span>
              <span class="ml-2 text-xs opacity-50">{{ k[1] }}</span>
            </button>
          }
        </mat-menu>
        <div class="flex items-center gap-2 md:gap-3 ml-auto">
          <button mat-icon-button (click)="loupeActive.set(!loupeActive())"
                  [class.!text-[var(--mat-sys-primary)]]="loupeActive()"
                  [attr.aria-pressed]="loupeActive()"
                  [matTooltip]="I18N.scenes.loupe_hint | translate"
                  [attr.aria-label]="I18N.scenes.loupe | translate">
            <mat-icon>{{ loupeActive() ? 'zoom_in' : 'search' }}</mat-icon>
          </button>
          @if (loupeActive()) {
            <mat-slider class="!w-28 !min-w-0" [min]="2" [max]="8" [step]="1" [discrete]="true">
              <input matSliderThumb [value]="loupeZoom()" (valueChange)="loupeZoom.set($event)"
                     [attr.aria-label]="I18N.scenes.loupe | translate" />
            </mat-slider>
          }
          @if (photos().length > 0) {
            <button mat-icon-button color="warn" (click)="rejectAllShown()"
                    [matTooltip]="I18N.junk.reject_all | translate:{ count: photos().length }"
                    [attr.aria-label]="I18N.junk.reject_all | translate:{ count: photos().length }">
              <mat-icon>delete_sweep</mat-icon>
            </button>
          }
        </div>
      </div>
    </ng-template>

    <div class="px-4 pt-3 md:px-8 mx-auto w-full max-w-[96%] max-lg:pb-24">
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
              <div class="absolute inset-x-0 bottom-0 flex justify-end items-center gap-1 p-1.5 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors text-green-400"
                  [matTooltip]="I18N.junk.keep_hint | translate"
                  [attr.aria-label]="I18N.junk.keep | translate"
                  (click)="keep(photo)">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">check</mat-icon>
                </button>
                <button
                  class="w-7 h-7 rounded-full inline-flex items-center justify-center hover:bg-white/20 transition-colors text-red-400"
                  [matTooltip]="I18N.junk.reject_hint | translate"
                  [attr.aria-label]="I18N.junk.reject | translate"
                  (click)="reject(photo)">
                  <mat-icon class="!text-base !w-4 !h-4 !leading-4" aria-hidden="true">delete</mat-icon>
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
export class JunkSweepComponent implements OnInit, OnDestroy {
  protected readonly I18N = I18N;
  protected readonly ANY_KIND = ANY_KIND;
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly dialog = inject(MatDialog);
  private readonly pageHelp = inject(PageHelpService);
  private readonly headerSlot = inject(HeaderSlotService);

  private readonly junkToolbar = viewChild<TemplateRef<unknown>>('junkToolbar');

  constructor() {
    effect(() => {
      const tpl = this.junkToolbar();
      if (tpl) this.headerSlot.set(tpl);
    });
  }

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
    this.pageHelp.setDescription(I18N.junk.help);
    void this.loadKinds();
    await this.load();
  }

  ngOnDestroy(): void {
    this.pageHelp.setDescription(null);
    const tpl = this.junkToolbar();
    if (tpl) this.headerSlot.clear(tpl);
  }

  private async loadKinds(): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.api.get<{ junk_kinds: [string, number][] }>('/filter_options/junk_kinds'),
      );
      this.kinds.set(data.junk_kinds ?? []);
    } catch {
      // The kind filter menu stays empty; the "All kinds" view still works.
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
      this.notifyError();
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
      this.notify(I18N.junk.kept, 1500);
    } catch {
      this.restoreLocal(photo);
      this.notifyError();
    }
  }

  /** Reject a candidate via the shared batch_reject plumbing (single path). */
  protected async reject(photo: JunkPhoto): Promise<void> {
    this.removeLocal(photo);
    try {
      await firstValueFrom(this.api.post('/photos/batch_reject', { photo_paths: [photo.path] }));
      this.notify(I18N.junk.rejected, 1500);
    } catch {
      this.restoreLocal(photo);
      this.notifyError();
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
      this.notify(I18N.junk.rejected_bulk, 2000, { count: paths.length });
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
      this.notifyError();
    }
  }

  private notify(key: string, duration: number, vars?: Record<string, string | number>): void {
    this.snack.open(this.i18n.t(key, vars), this.i18n.t(I18N.common.dismiss), { duration });
  }

  private notifyError(): void {
    this.notify(I18N.junk.load_error, 3000);
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
