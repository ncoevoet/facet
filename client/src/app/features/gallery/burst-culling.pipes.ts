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

/** A single detected face within a photo (from POST /api/culling-group/faces). */
export interface CullingFace {
  id: number;
  face_index: number;
  confidence?: number | null;
  eyes_open_score?: number | null;
  smile_score?: number | null;
  expression_score?: number | null;
  is_blink?: boolean;
}

/** Server-side face-signal cutoffs (scoring_config face_detection), returned by
 *  POST /api/culling-group/faces so the client never hardcodes them. */
export interface FaceThresholds {
  eyes_closed_max: number;
  poor_expression_min: number;
}

/** A single photo's subject close-up within a culling group
 *  (from POST /api/culling-group/subjects). One subject per photo. */
export interface CullingSubject {
  path: string;
  has_subject: boolean;
  /** Base64 data URI of the thumbnail cropped to the subject box, or null. */
  crop: string | null;
  subject_sharpness: number | null;
  subject_prominence: number | null;
  crop_sharpness: number | null;
  /** Group-normalized 0..10 sharpness (sharpest crop reads 10). */
  crop_sharpness_score: number | null;
}

/** A burst, similar, or scene group surfaced for culling. */
export interface CullingGroup {
  group_id: number;
  type: 'burst' | 'similar' | 'scene';
  reason: string;
  photos: CullingPhoto[];
  best_path: string;
  count: number;
  category?: string | null;
  /** Scene-only: capture-time window + dominant narrative moment (group_by=scene). */
  start?: string | null;
  end?: string | null;
  moment?: string | null;
  moment_confidence?: number | null;
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

/** Look up the loaded subject close-up for a photo path from the subject map. */
@Pipe({ name: 'subjectForPath' })
export class SubjectForPathPipe implements PipeTransform {
  transform(path: string, subjectMap: Map<string, CullingSubject>): CullingSubject | null {
    return subjectMap.get(path) ?? null;
  }
}

/** Tailwind ring color for a subject crop, ranking by the group-normalized
 *  sharpness score: green = sharpest tier, amber = mid, red = softest. */
@Pipe({ name: 'subjectRingClass' })
export class SubjectRingClassPipe implements PipeTransform {
  transform(subject: CullingSubject): string {
    const score = subject.crop_sharpness_score;
    if (score == null) return 'ring-white/20';
    if (score >= 8) return 'ring-green-500';
    if (score >= 5) return 'ring-amber-500';
    return 'ring-red-500';
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

/** True when a single face has a poor (wide-open) expression worth flagging.
 *  The cutoff comes from the server's `thresholds` object (config-driven). */
@Pipe({ name: 'facePoorExpression' })
export class FacePoorExpressionPipe implements PipeTransform {
  transform(face: CullingFace, thresholds: FaceThresholds | null): boolean {
    const expr = face.expression_score;
    return thresholds != null && expr != null && expr < thresholds.poor_expression_min;
  }
}

/** Tailwind ring color for a face crop: red = eyes closed, orange = poor smile,
 *  green = both signals fine, neutral when signals or thresholds are missing. */
@Pipe({ name: 'faceRingClass' })
export class FaceRingClassPipe implements PipeTransform {
  transform(face: CullingFace, thresholds: FaceThresholds | null): string {
    if (!thresholds) return 'ring-white/20';
    if (face.eyes_open_score != null && face.eyes_open_score <= thresholds.eyes_closed_max) {
      return 'ring-red-500';
    }
    if (face.smile_score != null && face.smile_score < thresholds.poor_expression_min) {
      return 'ring-orange-500';
    }
    if (face.eyes_open_score == null && face.smile_score == null) return 'ring-white/20';
    return 'ring-green-500';
  }
}

/** True when the live face-panel sliders are active and this face is NOT below
 *  either chosen value — such faces render dimmed so the below-threshold ones
 *  stand out. Slider value 0 = filter off. */
@Pipe({ name: 'faceDimmed' })
export class FaceDimmedPipe implements PipeTransform {
  transform(face: CullingFace, eyesMin: number, smileMin: number): boolean {
    if (eyesMin <= 0 && smileMin <= 0) return false;
    const belowEyes = eyesMin > 0 && face.eyes_open_score != null && face.eyes_open_score < eyesMin;
    const belowSmile = smileMin > 0 && face.smile_score != null && face.smile_score < smileMin;
    return !belowEyes && !belowSmile;
  }
}

/** Map a culling sort mode to its Material icon (per-item + trigger). */
@Pipe({ name: 'sortIcon' })
export class SortIconPipe implements PipeTransform {
  private static readonly ICONS: Record<string, string> = {
    easiest: 'bolt',
    redundant: 'content_copy',
    best: 'star',
    recent: 'schedule',
    needs_comparisons: 'compare_arrows',
  };

  transform(mode: string): string {
    return SortIconPipe.ICONS[mode] ?? 'sort';
  }
}

/** Map a content category to its Material icon, with a generic fallback for
 *  values outside the known vocabulary. */
@Pipe({ name: 'categoryIcon' })
export class CategoryIconPipe implements PipeTransform {
  private static readonly ICONS: Record<string, string> = {
    portrait: 'person',
    portrait_bw: 'filter_b_and_w',
    group_portrait: 'groups',
    human_others: 'people',
    silhouette: 'contrast',
    candid: 'mood',
    art: 'palette',
    abstract: 'blur_on',
    macro: 'zoom_in',
    astro: 'nights_stay',
    street: 'directions_walk',
    aerial: 'flight',
    concert: 'music_note',
    night: 'dark_mode',
    wildlife: 'pets',
    architecture: 'apartment',
    urban: 'location_city',
    food: 'restaurant',
    landscape: 'landscape',
    sports: 'sports_soccer',
    vehicle: 'directions_car',
    travel: 'luggage',
    fashion: 'checkroom',
    long_exposure: 'shutter_speed',
    cinematic: 'movie',
    vintage: 'filter_vintage',
    dramatic: 'flare',
    monochrome: 'tonality',
    weather: 'cloud',
    golden_hour: 'wb_twilight',
    blue_hour: 'bedtime',
    product: 'inventory_2',
    minimalist: 'crop_din',
    default: 'image',
  };

  transform(category: string | null | undefined): string {
    return (category && CategoryIconPipe.ICONS[category]) || 'category';
  }
}

/** Map a genre culling profile id to its Material icon; the shipped presets get
 *  a distinct icon, config-defined custom profiles fall back to the theatre mask. */
@Pipe({ name: 'cullProfileIcon' })
export class CullProfileIconPipe implements PipeTransform {
  private static readonly ICONS: Record<string, string> = {
    balanced: 'balance',
    wedding: 'favorite',
    sports: 'directions_run',
    concert: 'music_note',
    wildlife: 'pets',
  };

  transform(profileId: string | null | undefined): string {
    return (profileId && CullProfileIconPipe.ICONS[profileId]) || 'theaters';
  }
}

/** Map a culling granularity / group kind to its Material icon. */
@Pipe({ name: 'cullGroupIcon' })
export class CullGroupIconPipe implements PipeTransform {
  private static readonly ICONS: Record<string, string> = {
    all: 'dashboard',
    burst: 'burst_mode',
    similar: 'filter_none',
    scene: 'movie_filter',
  };

  transform(kind: string): string {
    return CullGroupIconPipe.ICONS[kind] ?? 'dashboard';
  }
}

/** Map a culling group kind to its localized name key (for tooltips / labels). */
@Pipe({ name: 'cullGroupLabel' })
export class CullGroupLabelPipe implements PipeTransform {
  private static readonly KEYS: Record<string, string> = {
    burst: 'culling.group_by.bursts',
    similar: 'culling.group_by.similar',
    scene: 'culling.group_by.scenes',
  };

  transform(kind: string): string {
    return CullGroupLabelPipe.KEYS[kind] ?? '';
  }
}

/** A configured darktable style for the edited-look cull preview. */
export interface CullStyle {
  name: string;
  label_key: string;
}

/** Build the cull-preview endpoint URL for a photo rendered through a darktable style. */
export function cullPreviewUrl(path: string, style: string): string {
  const params = new URLSearchParams({ path, style });
  return `/api/photo/cull_preview?${params}`;
}

@Pipe({ name: 'cullPreviewUrl' })
export class CullPreviewUrlPipe implements PipeTransform {
  transform(path: string, style: string): string {
    return cullPreviewUrl(path, style);
  }
}
