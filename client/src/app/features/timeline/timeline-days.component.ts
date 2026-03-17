import { Component, inject, signal, input, effect, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

interface DateEntry {
  date: string;
  count: number;
  hero_photo_path: string | null;
}

interface CalendarCell {
  date: string | null;
  day: number;
  count: number;
  hero_photo_path: string | null;
}

@Component({
  selector: 'app-timeline-days',
  standalone: true,
  imports: [MatIconModule, MatProgressSpinnerModule, ThumbnailUrlPipe],
  template: `
    @if (loading()) {
      <div class="flex justify-center py-16">
        <mat-spinner diameter="48" />
      </div>
    }

    @if (!loading()) {
      <!-- Day-of-week headers -->
      <div class="grid grid-cols-7 gap-1 mb-1 max-w-3xl mx-auto">
        @for (d of weekDays; track d) {
          <div class="text-center text-xs font-medium opacity-50 py-1">{{ d }}</div>
        }
      </div>

      <!-- Calendar grid -->
      <div class="grid grid-cols-7 gap-1 max-w-3xl mx-auto">
        @for (cell of calendarCells(); track $index) {
          @if (cell.date) {
            <button
              class="relative rounded-lg overflow-hidden transition-shadow cursor-pointer aspect-square"
              [class]="cell.count > 0 ? 'hover:shadow-lg bg-[var(--mat-sys-surface-container)]' : 'opacity-40 bg-[var(--mat-sys-surface-container)] cursor-default'"
              (click)="cell.count > 0 && daySelected.emit(cell.date)">
              @if (cell.hero_photo_path) {
                <img [src]="cell.hero_photo_path | thumbnailUrl:160"
                     class="absolute inset-0 w-full h-full object-cover" loading="lazy" />
                <div class="absolute inset-0 bg-black/30"></div>
              }
              <div class="relative z-10 flex flex-col items-center justify-center h-full p-1"
                   [class.text-white]="!!cell.hero_photo_path">
                <span class="text-sm font-semibold">{{ cell.day }}</span>
                @if (cell.count > 0) {
                  <span class="text-[10px] opacity-70">{{ cell.count }}</span>
                }
              </div>
            </button>
          } @else {
            <!-- Empty cell (padding for first week) -->
            <div class="aspect-square"></div>
          }
        }
      </div>
    }
  `,
})
export class TimelineDaysComponent {
  private readonly api = inject(ApiService);

  readonly year = input.required<string>();
  readonly month = input.required<string>();
  readonly daySelected = output<string>();

  protected readonly calendarCells = signal<CalendarCell[]>([]);
  protected readonly loading = signal(false);

  protected readonly weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  constructor() {
    effect(() => {
      const y = this.year();
      const m = this.month();
      if (y && m) this.load(+y, +m);
    });
  }

  private async load(year: number, month: number): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(
        this.api.get<{ dates: DateEntry[] }>('/timeline/dates', { year, month }),
      );

      // Build date lookup
      const dateMap = new Map<string, DateEntry>();
      for (const d of res.dates) {
        dateMap.set(d.date, d);
      }

      // Build calendar cells
      const firstDay = new Date(year, month - 1, 1);
      const daysInMonth = new Date(year, month, 0).getDate();
      // Monday=0, Sunday=6
      let startDow = firstDay.getDay() - 1;
      if (startDow < 0) startDow = 6;

      const cells: CalendarCell[] = [];
      // Padding cells for days before the 1st
      for (let i = 0; i < startDow; i++) {
        cells.push({ date: null, day: 0, count: 0, hero_photo_path: null });
      }

      for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const entry = dateMap.get(dateStr);
        cells.push({
          date: dateStr,
          day: d,
          count: entry?.count ?? 0,
          hero_photo_path: entry?.hero_photo_path ?? null,
        });
      }

      this.calendarCells.set(cells);
    } finally {
      this.loading.set(false);
    }
  }
}
