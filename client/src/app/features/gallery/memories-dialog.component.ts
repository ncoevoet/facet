import { Component, inject, signal, OnInit } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

interface MemoryPhoto {
  path: string;
  filename: string;
  aggregate: number | null;
  date_taken: string;
  date_formatted: string;
}

interface MemoryYear {
  year: string;
  photos: MemoryPhoto[];
  total_count: number;
}

interface MemoriesResponse {
  years: MemoryYear[];
  has_memories: boolean;
  date: string;
}

@Component({
  selector: 'app-memories-dialog',
  standalone: true,
  imports: [
    MatDialogModule, MatButtonModule, MatIconModule, MatProgressSpinnerModule,
    TranslatePipe, ThumbnailUrlPipe, DecimalPipe,
  ],
  template: `
    <h2 mat-dialog-title class="!flex items-center gap-2 truncate">
      <mat-icon>auto_awesome</mat-icon>
      <span class="flex-1">{{ 'memories.title' | translate }}</span>
      <button mat-icon-button mat-dialog-close class="shrink-0 !-mt-1 !-mr-2">
        <mat-icon>close</mat-icon>
      </button>
    </h2>
    <mat-dialog-content class="!max-h-[70vh] !min-w-[400px]">
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" />
        </div>
      } @else if (years().length === 0) {
        <div class="flex flex-col items-center gap-2 py-8 opacity-60">
          <mat-icon class="!text-4xl !w-10 !h-10">photo_library</mat-icon>
          <p class="text-sm">{{ 'memories.no_memories' | translate }}</p>
        </div>
      } @else {
        @for (yearGroup of years(); track yearGroup.year) {
          <div class="mb-5">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-lg font-semibold">{{ yearGroup.year }}</span>
              <span class="text-xs opacity-50">
                {{ yearGroup.total_count }} {{ 'memories.photos_count' | translate }}
              </span>
            </div>
            <div class="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1">
              @for (photo of yearGroup.photos; track photo.path) {
                <button
                  class="relative shrink-0 rounded-lg overflow-hidden group/mem cursor-pointer border-2 border-transparent hover:border-[var(--mat-sys-primary)] transition-colors"
                  (click)="onPhotoClick(photo)">
                  <img
                    [src]="photo.path | thumbnailUrl"
                    [alt]="photo.filename"
                    class="w-32 h-32 object-cover"
                    loading="lazy" />
                  <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-1.5 opacity-0 group-hover/mem:opacity-100 transition-opacity">
                    @if (photo.aggregate !== null) {
                      <span class="text-xs text-white font-medium">{{ photo.aggregate | number:'1.1-1' }}</span>
                    }
                  </div>
                </button>
              }
            </div>
          </div>
        }
      }
    </mat-dialog-content>
  `,
})
export class MemoriesDialogComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly dialogRef = inject(MatDialogRef<MemoriesDialogComponent>);
  private readonly data = inject<{ date?: string }>(MAT_DIALOG_DATA, { optional: true });

  protected readonly loading = signal(true);
  protected readonly years = signal<MemoryYear[]>([]);

  async ngOnInit(): Promise<void> {
    try {
      const params: Record<string, string> = {};
      if (this.data?.date) {
        params['date'] = this.data.date;
      }
      const res = await firstValueFrom(
        this.api.get<MemoriesResponse>('/memories', params),
      );
      this.years.set(res.years ?? []);
    } catch {
      this.years.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  protected onPhotoClick(photo: MemoryPhoto): void {
    this.dialogRef.close();

    // Extract the date (YYYY-MM-DD) from date_taken (EXIF format: YYYY:MM:DD HH:MM:SS)
    const dt = photo.date_taken;
    if (!dt) return;

    const dateOnly = dt.substring(0, 10).replace(/:/g, '-');
    this.router.navigate(['/'], {
      queryParams: {
        date_from: dateOnly,
        date_to: dateOnly,
      },
    });
  }
}
