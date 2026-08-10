import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

/**
 * The detector's full threshold block.
 *
 * Every field is carried even though the tab only exposes four: the PUT
 * replaces the block wholesale and 422s on a partial body, deliberately, so a
 * form that dropped a field cannot silently reset it.
 */
export interface PanoramaSettings {
  enabled: boolean;
  max_gap_seconds: number;
  min_frames: number;
  min_inliers: number;
  min_drift: number;
  max_step: number;
  back_tolerance: number;
  max_ortho: number;
  ortho_ratio: number;
  step_ortho_abs: number;
  step_ortho_ratio: number;
  sift_features: number;
  match_ratio: number;
  probe_stride: number;
  probe_min_drift: number;
  workers: number;
  max_run_frames: number;
  hdr_min_span_stops: number;
}

@Injectable({ providedIn: 'root' })
export class PanoramaSettingsService {
  private readonly http = inject(HttpClient);

  load(): Observable<PanoramaSettings> {
    return this.http
      .get<{ settings: PanoramaSettings }>('/api/config/panorama_detection')
      .pipe(map(r => r.settings));
  }

  save(settings: PanoramaSettings): Observable<{ message?: string }> {
    return this.http.put<{ message?: string }>('/api/config/panorama_detection', settings);
  }

  /** Detection is a batch pass, so a saved threshold reaches the gallery only after this. */
  redetect(): Observable<{ message?: string }> {
    return this.http.post<{ message?: string }>('/api/scan/detect_panoramas', { confirm: true });
  }
}
