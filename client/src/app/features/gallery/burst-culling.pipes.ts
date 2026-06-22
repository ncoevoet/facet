import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

/** Backend-supplied machine reason key + optional value for why a photo ranks lower. */
export interface CullReason {
  key: string;
  value: number | null;
}

/** A single photo within a burst/similar culling group. */
export interface CullingPhoto {
  path: string;
  filename: string;
  aggregate: number | null;
  aesthetic: number | null;
  tech_sharpness: number | null;
  is_blink: number;
  is_burst_lead: number;
  date_taken: string | null;
  burst_score: number;
  eyes_open_score?: number | null;
  expression_score?: number | null;
  cull_reason?: CullReason;
}

/** A single detected face within a photo (from GET /api/photo/faces). */
export interface CullingFace {
  id: number;
  face_index: number;
}

/** A burst or similar group surfaced for culling. */
export interface CullingGroup {
  group_id: number;
  type: 'burst' | 'similar';
  reason: string;
  photos: CullingPhoto[];
  best_path: string;
  count: number;
  category?: string | null;
}

@Pipe({ name: 'isKept' })
export class IsKeptPipe implements PipeTransform {
  transform(path: string, selectionsMap: Map<number, Set<string>>, burstId: number): boolean {
    const kept = selectionsMap.get(burstId);
    return kept?.has(path) ?? false;
  }
}

@Pipe({ name: 'isDecided' })
export class IsDecidedPipe implements PipeTransform {
  transform(path: string, selectionsMap: Map<number, Set<string>>, burstId: number): boolean {
    const kept = selectionsMap.get(burstId);
    return kept !== undefined && kept.size > 0 && !kept.has(path);
  }
}

@Pipe({ name: 'isConfirmed' })
export class IsConfirmedPipe implements PipeTransform {
  transform(group: CullingGroup, confirmedGroups: Set<string>): boolean {
    return confirmedGroups.has(`${group.group_id}_${group.type}`);
  }
}

@Pipe({ name: 'isPassing' })
export class IsPassingPipe implements PipeTransform {
  transform(group: CullingGroup, passingGroups: Map<string, number>): boolean {
    return passingGroups.has(`${group.group_id}_${group.type}`);
  }
}

@Pipe({ name: 'passCountdown' })
export class PassCountdownPipe implements PipeTransform {
  transform(group: CullingGroup, passingGroups: Map<string, number>): number {
    return passingGroups.get(`${group.group_id}_${group.type}`) ?? 0;
  }
}

/** Translate a backend cull-reason code into a localized, human-readable label. */
@Pipe({ name: 'cullReason', pure: false })
export class CullReasonPipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(reason: CullReason | undefined): string {
    if (!reason?.key) return '';
    const vars = reason.value != null ? { value: reason.value } : undefined;
    return this.i18n.t(`culling.reason.${reason.key}`, vars);
  }
}

/** Look up the loaded faces for a photo path from the face map. */
@Pipe({ name: 'facesForPath' })
export class FacesForPathPipe implements PipeTransform {
  transform(path: string, faceMap: Map<string, CullingFace[]>): CullingFace[] {
    return faceMap.get(path) ?? [];
  }
}

/** Per-category comparison count + threshold, for the weight-tuning progress chip. */
export interface WeightStats {
  category_breakdown?: { category: string; count: number }[];
  min_comparisons_for_optimization?: number;
}

/**
 * Comparisons still needed in a category before weight optimization unlocks.
 * Returns 0 (falsy) once the threshold is met, so the template's `@else` branch
 * renders the "ready" state.
 */
@Pipe({ name: 'weightRemaining' })
export class WeightRemainingPipe implements PipeTransform {
  /** Mirrors scoring_config viewer.comparison_mode.min_comparisons_for_optimization. */
  private static readonly DEFAULT_THRESHOLD = 50;

  transform(category: string | null | undefined, stats: WeightStats | null): number {
    if (!category || !stats) return 0;
    const threshold = stats.min_comparisons_for_optimization ?? WeightRemainingPipe.DEFAULT_THRESHOLD;
    const count = stats.category_breakdown?.find(c => c.category === category)?.count ?? 0;
    return Math.max(0, threshold - count);
  }
}

/** True when a photo's faces should be flagged as eyes-closed/blink. */
@Pipe({ name: 'isEyesClosed' })
export class IsEyesClosedPipe implements PipeTransform {
  /** Threshold mirrors the backend _CULL_EYES_CLOSED_MAX (eyes_open_score 0-10). */
  private static readonly EYES_CLOSED_MAX = 4.0;

  transform(photo: CullingPhoto): boolean {
    if (photo.is_blink) return true;
    const eyes = photo.eyes_open_score;
    return eyes != null && eyes <= IsEyesClosedPipe.EYES_CLOSED_MAX;
  }
}
