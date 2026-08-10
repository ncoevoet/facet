import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import { ApiService } from './api.service';

/** Kinds a set can be forced to; omitting one suppresses the set instead. */
export type SequenceKind = 'panorama' | 'hdr_panorama';

export interface SequenceOverrideResult {
  success: boolean;
  overridden: number;
  skipped: number;
  kind: SequenceKind | null;
}

/**
 * Manual corrections to what a set of frames is.
 *
 * Geometry cannot recover intent — a deliberate sweep and a pan following a
 * moving subject are the same measurement — so both error directions need a
 * human, and both are expressed here: suppressing a detected set, or forcing
 * one the detector never grouped.
 *
 * Nothing here relabels a photo. The correction is sticky in
 * `photo_sequence_overrides` and only reaches `photos.sequence_kind` at the
 * next detection run, which is a whole-library batch pass.
 *
 * Lives in core because the culling feed corrects false positives and the
 * gallery corrects misses; an undetected sweep appears in no culling group, so
 * neither surface alone covers both directions.
 */
@Injectable({ providedIn: 'root' })
export class SequenceOverrideService {
  private readonly api = inject(ApiService);

  /** Record a correction. Omit `kind` to suppress ("this is not a panorama"). */
  set(paths: string[], kind?: SequenceKind): Observable<SequenceOverrideResult> {
    return this.api.post<SequenceOverrideResult>(
      '/culling-groups/override_sequence', { paths, kind: kind ?? null });
  }

  /** Hand the frames back to the detector. */
  clear(paths: string[]): Observable<{ success: boolean; cleared: number }> {
    return this.api.post<{ success: boolean; cleared: number }>(
      '/culling-groups/clear_sequence_override', { paths });
  }

  setAsync(paths: string[], kind?: SequenceKind): Promise<SequenceOverrideResult> {
    return firstValueFrom(this.set(paths, kind));
  }

  clearAsync(paths: string[]): Promise<{ success: boolean; cleared: number }> {
    return firstValueFrom(this.clear(paths));
  }
}
