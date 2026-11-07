import { Pipe, PipeTransform } from '@angular/core';
import { FEATURE_MARK, MarkTonePipe } from './mark-tone.pipe';

/** Decorative hints only: translated option text remains the sort's label. */
export const SORT_ICONS: Readonly<Record<string, string>> = {
  relevance: 'search',
  learned_score: 'psychology',
  top_picks_score: 'recommend',
  aggregate: 'leaderboard',
  aesthetic: FEATURE_MARK,
  quality_score: 'high_quality',
  date_taken: 'event',
  star_rating: 'star',
  face_quality: 'portrait',
  eye_sharpness: 'visibility',
  face_sharpness: 'face',
  face_ratio: 'crop_portrait',
  face_count: 'groups',
  tech_sharpness: 'deblur',
  contrast_score: 'contrast',
  noise_sigma: 'grain',
  color_score: 'palette',
  mean_saturation: 'gradient',
  exposure_score: 'exposure',
  mean_luminance: 'brightness_6',
  histogram_spread: 'bar_chart',
  dynamic_range_stops: 'tonality',
  comp_score: 'grid_on',
  power_point_score: 'grid_3x3',
  leading_lines_score: 'timeline',
  isolation_bonus: 'filter_tilt_shift',
  composition_pattern: 'grid_view',
  subject_sharpness: 'center_focus_strong',
  subject_prominence: 'photo_size_select_large',
  subject_placement: 'control_camera',
  bg_separation: 'blur_on',
  form_symmetry: 'flip',
  form_balance: 'balance',
  form_edge_entropy: 'texture',
  form_fractal: 'hub',
  color_harmony: 'color_lens',
  topiq_score: 'high_quality',
  face_confidence: 'verified_user',
  aesthetic_iaa: 'brush',
  face_quality_iqa: 'face_retouching_natural',
  liqe_score: 'visibility',
  narrative_moment_confidence: 'auto_stories',
  f_stop: 'camera',
  focal_length: 'zoom_in',
  shutter_speed: 'shutter_speed',
};

const MODEL_LABELS: Readonly<Record<string, string>> = {
  aesthetic_iaa: 'IAA',
  aesthetic_v25: '2.5',
  qrealign_score: 'Q-R',
  deqa_score: 'DeQA',
  liqe_score: 'LIQE',
  face_quality_iqa: 'IQA',
};

/** A model label is short text set in the icon slot, so it drops the icon font and shrinks to fit. */
const MODEL_LABEL_CLASSES = '!font-sans !text-[11px] !font-semibold !leading-6';

const MARK_TONE = new MarkTonePipe();

export interface SortOptionIcon {
  text: string;
  /** Extra classes for the `mat-icon` showing `text`: the colour of a feature's ✦, else empty for a Material icon. */
  classes: string;
}

@Pipe({ name: 'sortOptionIcon', standalone: true, pure: true })
export class SortOptionIconPipe implements PipeTransform {
  transform(column: string): SortOptionIcon {
    if (Object.hasOwn(MODEL_LABELS, column)) return { text: MODEL_LABELS[column], classes: MODEL_LABEL_CLASSES };
    if (!Object.hasOwn(SORT_ICONS, column)) return { text: 'sort', classes: '' };
    return { text: SORT_ICONS[column], classes: MARK_TONE.transform(column) };
  }
}
