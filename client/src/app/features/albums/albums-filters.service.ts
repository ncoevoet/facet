import { Injectable, signal } from '@angular/core';

export type AlbumSortField = 'name' | 'photo_count' | 'updated_at';
export type AlbumTypeFilter = '' | 'manual' | 'smart';

@Injectable({ providedIn: 'root' })
export class AlbumsFiltersService {
  readonly search = signal('');
  readonly sort = signal<AlbumSortField>('updated_at');
  readonly typeFilter = signal<AlbumTypeFilter>('');
  readonly createRequested = signal(0);
}
