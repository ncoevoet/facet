import { Injectable, signal } from '@angular/core';

export interface StatsOverviewData {
  total_photos: number;
  total_persons: number;
  avg_score: number;
  avg_aesthetic: number;
  avg_composition: number;
  total_faces: number;
  total_tags: number;
  date_range_start: string;
  date_range_end: string;
}

@Injectable({ providedIn: 'root' })
export class StatsFiltersService {
  readonly filterCategory = signal('');
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  readonly overview = signal<StatsOverviewData | null>(null);
}
