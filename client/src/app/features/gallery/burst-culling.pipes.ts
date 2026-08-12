import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';
import { SEQUENCE_KIND_ICONS } from '../../shared/pipes/sequence-kind.pipe';

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
  /** Set when the frame belongs to a deliberate multi-frame sequence ('bracket'). */
  sequence_kind?: string | null;
  /** Stops away from that sequence's base exposure; 0 on the base frame itself. */
  sequence_ev_offset?: number | null;
  /** A manual correction to the set: 'suppressed' ("not a panorama") or the
   *  kind it was forced to. Set for as long as the correction stands. */
  sequence_override?: string | null;
  /** Whether that correction is still waiting on a detection run. */
  sequence_override_pending?: number | null;
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

/** A burst, similar, scene, bracket or panorama group surfaced for culling. */
export interface CullingGroup {
  group_id: number;
  type: 'burst' | 'similar' | 'scene' | 'bracket' | 'panorama' | 'hdr_panorama';
  reason: string;
  photos: CullingPhoto[];
  best_path: string;
  count: number;
  category?: string | null;
  /** Set only when EVERY frame belongs to one sequence, so the group is not a set
   *  of competing takes to choose between. */
  sequence_kind?: string | null;
  /** Scene-only: capture-time window + dominant narrative moment (group_by=scene). */
  start?: string | null;
  end?: string | null;
  moment?: string | null;
  moment_confidence?: number | null;
}

/** Render a bracket frame's exposure offset as a signed badge ("+2 EV", "0 EV").
 *  The sign is the whole point -- it says which rung of the ladder a frame is. */
@Pipe({ name: 'evOffset' })
export class EvOffsetPipe implements PipeTransform {
  transform(stops: number | null | undefined): string {
    if (stops === null || stops === undefined || Number.isNaN(stops)) return '';
    const rounded = Math.round(stops * 10) / 10;
    const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '';
    return `${sign}${Math.abs(rounded)} EV`;
  }
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

/** The only coordinate space the key-subject endpoints answer in: every box is
 *  [x0, y0, x1, y1] in fractions of the FULL frame, origin top-left — never of
 *  the thumbnail on screen, and never pixels. Multiply by the rendered size. */
export const KEY_SUBJECT_COORDINATE_SPACE = 'normalized_frame_xyxy';

/** Who / what a photo is about, resolved server-side from its faces and its
 *  persisted saliency box (GET /api/photo/key_subject,
 *  POST /api/photos/key_subjects). Every requested path comes back, an
 *  unknown or invisible one as `kind: 'none'`. */
export interface KeySubject {
  path: string;
  /** 'person' = a detected face won; 'subject' = the BiRefNet saliency box;
   *  'none' = neither, so there is nothing to zoom at or badge. */
  kind: 'person' | 'subject' | 'none';
  /** Always KEY_SUBJECT_COORDINATE_SPACE. */
  coordinate_space: string;
  /** The frame the fractions were measured against — NOT the size on screen. */
  image_width: number | null;
  image_height: number | null;
  bbox: [number, number, number, number] | null;
  /** [cx, cy] centre of bbox, same space: the zoom target. Null for 'none'. */
  center: [number, number] | null;
  area_ratio: number | null;
  centrality: number | null;
  /** Face ranking score, 0..1. Null for kind 'subject'. */
  score: number | null;
  /** Matches CullingFace.id — how the key-person badge finds its face. */
  face_id: number | null;
  face_index: number | null;
  /** Null for an unassigned OR hidden cluster; a null person_name also means
   *  "do not badge", since there is no name to show. */
  person_id: number | null;
  person_name: string | null;
  /** Only filled for kind 'subject' — they grade the saliency box, not a face. */
  subject_sharpness: number | null;
  subject_prominence: number | null;
  subject_placement: number | null;
  bg_separation: number | null;
}

/** Look up the resolved key subject for a photo path from the key-subject map. */
@Pipe({ name: 'keySubjectForPath' })
export class KeySubjectForPathPipe implements PipeTransform {
  transform(path: string, keySubjectMap: Map<string, KeySubject>): KeySubject | null {
    return keySubjectMap.get(path) ?? null;
  }
}

/** True when this face crop is the one the photo's key subject resolved to. */
@Pipe({ name: 'isKeyFace' })
export class IsKeyFacePipe implements PipeTransform {
  transform(face: CullingFace, key: KeySubject | null): boolean {
    return !!key && key.kind === 'person' && key.face_id === face.id;
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
    chronological: 'history',
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
    ...SEQUENCE_KIND_ICONS,
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
    bracket: 'culling.group_by.brackets',
    panorama: 'culling.group_by.panoramas',
    hdr_panorama: 'culling.group_by.hdr_panoramas',
  };

  transform(kind: string): string {
    return CullGroupLabelPipe.KEYS[kind] ?? '';
  }
}

/**
 * A group's manual correction, or '' when it carries none.
 *
 * Read off the frames rather than stored on the group: the correction lives
 * per-photo in `photo_sequence_overrides`, and a set is only ever corrected
 * whole, so the first frame carrying one speaks for the group.
 */
@Pipe({ name: 'groupOverride' })
export class GroupOverridePipe implements PipeTransform {
  transform(group: CullingGroup): string {
    return group.photos.find(p => p.sequence_override)?.sequence_override ?? '';
  }
}

/**
 * A group's correction that the detector has not applied yet, or ''.
 *
 * Distinct from `groupOverride`: the correction stays stored once applied, so
 * only this one may drive anything that says "pending".
 */
@Pipe({ name: 'groupOverridePending' })
export class GroupOverridePendingPipe implements PipeTransform {
  transform(group: CullingGroup): string {
    const photo = group.photos.find(p => p.sequence_override && p.sequence_override_pending);
    return photo?.sequence_override ?? '';
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

// --- Darkroom overlays: focus peaking + composition grid ---

/** Natural pixel size of a displayed frame. */
export interface FrameSize {
  w: number;
  h: number;
}

/** Composition grid states, in the order the toggle cycles them. */
export type GridMode = '' | 'thirds' | 'golden';
export const GRID_MODES: readonly GridMode[] = ['', 'thirds', 'golden'];

/** Where each grid draws its lines, as SVG percentage lengths so the same list
 *  serves both axes whatever viewBox the frame ends up with. */
const GRID_LINES: Record<string, string[]> = {
  thirds: ['33.333%', '66.667%'],
  golden: ['38.197%', '61.803%'],
};

/** Working-canvas pixel budget for the edge map: a 2 MP convolution stays under
 *  a frame's worth of latency, and peaking is judged at screen resolution. */
const PEAKING_MAX_PIXELS = 2_000_000;
/** Absolute gradient floor, on the 0-255 Sobel scale: what counts as "in focus"
 *  at all. It is the primary threshold, and being absolute it is the only reason
 *  two frames of the same subject can be compared by how much red each shows. */
const PEAKING_MIN_EDGE = 24;
/** Share of the frame the paint may cover before the floor is raised. A relief
 *  valve for frames that are edge everywhere (noise, foliage, fabric), never the
 *  driver: measured on library frames at this working size, a sharp frame paints
 *  2-3% and its defocused copy 0.3%, so the cap does not engage and coverage is
 *  a purely absolute -- therefore comparable -- reading of in-focus detail. */
const PEAKING_MAX_COVERAGE = 0.15;
const PEAKING_COLOR = [255, 32, 32] as const;
const PEAKING_HISTOGRAM_BINS = 256;

/**
 * Paint the in-focus edges of an RGBA frame red and everything else clear.
 *
 * A 3x3 Sobel over luma, thresholded at the absolute ``PEAKING_MIN_EDGE``
 * gradient, raised only when the paint would cover more than
 * ``PEAKING_MAX_COVERAGE`` of the frame. Pure over pixel data — the canvas work
 * lives in ``computePeakingOverlay`` — so the decision this makes is testable
 * without a rendering surface.
 */
export function peakingEdgeOverlay(
  pixels: Uint8ClampedArray, width: number, height: number,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(width * height * 4);
  if (width < 3 || height < 3) return out;

  const luma = new Float32Array(width * height);
  for (let i = 0; i < luma.length; i++) {
    const p = i * 4;
    luma[i] = 0.299 * pixels[p] + 0.587 * pixels[p + 1] + 0.114 * pixels[p + 2];
  }

  const magnitude = new Float32Array(width * height);
  const histogram = new Uint32Array(PEAKING_HISTOGRAM_BINS);
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const tl = luma[i - width - 1], t = luma[i - width], tr = luma[i - width + 1];
      const l = luma[i - 1], r = luma[i + 1];
      const bl = luma[i + width - 1], b = luma[i + width], br = luma[i + width + 1];
      const gx = (tr + 2 * r + br) - (tl + 2 * l + bl);
      const gy = (bl + 2 * b + br) - (tl + 2 * t + tr);
      const mag = Math.min(255, Math.hypot(gx, gy) / 4);
      magnitude[i] = mag;
      histogram[Math.round(mag)] += 1;
    }
  }

  // Walk the strongest gradients down towards the floor and stop one bin above
  // the one that would outgrow the cap, so coverage stays under it. The clamp
  // matters for a saturated frame (a document, a graphic): every gradient sits in
  // the top bin there, and without it the sharpest frame there is would go blank.
  const maxLit = (width - 2) * (height - 2) * PEAKING_MAX_COVERAGE;
  let threshold = PEAKING_MIN_EDGE;
  let lit = 0;
  for (let bin = PEAKING_HISTOGRAM_BINS - 1; bin > PEAKING_MIN_EDGE; bin--) {
    lit += histogram[bin];
    if (lit > maxLit) {
      threshold = Math.min(PEAKING_HISTOGRAM_BINS - 1, bin + 1);
      break;
    }
  }

  for (let i = 0; i < magnitude.length; i++) {
    if (magnitude[i] < threshold) continue;
    const p = i * 4;
    out[p] = PEAKING_COLOR[0];
    out[p + 1] = PEAKING_COLOR[1];
    out[p + 2] = PEAKING_COLOR[2];
    out[p + 3] = 255;
  }
  return out;
}

/** Load an image for off-screen raster work; rejects when the source fails. */
export function loadFrameImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`cannot load ${src}`));
    img.src = src;
  });
}

/**
 * Build the focus-peaking overlay for one frame as a PNG data URL.
 *
 * Rendered into an image rather than a live canvas so the overlay inherits the
 * frame's own ``object-contain`` letterboxing: the working canvas keeps the
 * source aspect ratio, so the two land on exactly the same pixels under the
 * same transform, with no per-pane measurement.
 */
export async function computePeakingOverlay(src: string): Promise<string | null> {
  const img = await loadFrameImage(src);
  const naturalW = img.naturalWidth || img.width;
  const naturalH = img.naturalHeight || img.height;
  if (!naturalW || !naturalH) return null;
  const scale = Math.min(1, Math.sqrt(PEAKING_MAX_PIXELS / (naturalW * naturalH)));
  const width = Math.max(1, Math.round(naturalW * scale));
  const height = Math.max(1, Math.round(naturalH * scale));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0, width, height);
  const frame = ctx.getImageData(0, 0, width, height);
  const overlay = ctx.createImageData(width, height);
  overlay.data.set(peakingEdgeOverlay(frame.data, width, height));
  ctx.putImageData(overlay, 0, 0);
  return canvas.toDataURL('image/png');
}

/** The generated peaking overlay for a frame, or null while none exists. */
@Pipe({ name: 'peakingOverlay' })
export class PeakingOverlayPipe implements PipeTransform {
  transform(path: string, overlays: Map<string, string>): string | null {
    return overlays.get(path) ?? null;
  }
}

/** A frame's SVG viewBox, so a grid drawn in it letterboxes exactly like the
 *  `object-contain` image it sits on. Null until the size is known. */
@Pipe({ name: 'frameViewBox' })
export class FrameViewBoxPipe implements PipeTransform {
  transform(path: string, sizes: Map<string, FrameSize>): string | null {
    const size = sizes.get(path);
    return size ? `0 0 ${size.w} ${size.h}` : null;
  }
}

/** The line positions of a composition grid; empty when the grid is off. */
@Pipe({ name: 'gridLines' })
export class GridLinesPipe implements PipeTransform {
  transform(mode: GridMode): string[] {
    return GRID_LINES[mode] ?? [];
  }
}
