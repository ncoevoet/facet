import { inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from './api.service';

/**
 * Whether the library holds any photo the current user can see on the map.
 * The shell reads it to show the Map link; every client GPS write calls
 * `refresh()` so a first location shows the link (and clearing the last one
 * hides it) without a reload.
 */
@Injectable({ providedIn: 'root' })
export class GeoPhotosService {
  private readonly api = inject(ApiService);
  private sequence = 0;
  readonly available = signal(false);

  async refresh(): Promise<void> {
    const request = ++this.sequence;
    try {
      const data = await firstValueFrom(this.api.get<{ count: number }>('/photos/map/count'));
      // A slower, older answer must not overwrite a newer one.
      if (request === this.sequence) this.available.set(data.count > 0);
    } catch { /* Non-critical: keep the last known state */ }
  }
}
