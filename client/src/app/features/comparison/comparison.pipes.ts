import { Pipe, PipeTransform } from '@angular/core';

const WEIGHT_ICONS: Record<string, string> = {
  aesthetic_percent: 'auto_awesome',
  composition_percent: 'grid_on',
  face_quality_percent: 'face',
  face_sharpness_percent: 'face_retouching_natural',
  eye_sharpness_percent: 'visibility',
  tech_sharpness_percent: 'center_focus_strong',
  exposure_percent: 'exposure',
  color_percent: 'palette',
  quality_percent: 'high_quality',
  contrast_percent: 'contrast',
  dynamic_range_percent: 'hdr_strong',
  saturation_percent: 'water_drop',
  noise_percent: 'grain',
  isolation_percent: 'filter_center_focus',
  power_point_percent: 'my_location',
  leading_lines_percent: 'timeline',
  // Supplementary PyIQA
  aesthetic_iaa_percent: 'art_track',
  face_quality_iqa_percent: 'face_4',
  liqe_percent: 'analytics',
  // Subject saliency
  subject_sharpness_percent: 'blur_off',
  subject_prominence_percent: 'fullscreen',
  subject_placement_percent: 'place',
  bg_separation_percent: 'blur_on',
};

@Pipe({ name: 'weightIcon', standalone: true, pure: true })
export class WeightIconPipe implements PipeTransform {
  transform(key: string): string {
    return WEIGHT_ICONS[key] ?? 'tune';
  }
}

@Pipe({ name: 'weightLabelKey', standalone: true, pure: true })
export class WeightLabelKeyPipe implements PipeTransform {
  transform(key: string): string {
    return 'comparison.dim.' + key.replace('_percent', '');
  }
}

/**
 * Formats a numeric filter value for display based on its key.
 * Shutter speed: 1/500, 2.0s; Aperture: f/2.8; Focal length: 50mm; ISO: ISO 800;
 * Face ratio / luminance: 50%; Face count: integer.
 */
@Pipe({ name: 'filterValueFormat', standalone: true, pure: true })
export class FilterValueFormatPipe implements PipeTransform {
  transform(value: number | null | undefined, key: string): string {
    if (value == null || isNaN(value)) return '';
    if (key.startsWith('shutter_speed')) {
      if (value <= 0) return '';
      return value >= 1 ? value.toFixed(1) + 's' : '1/' + Math.round(1 / value);
    }
    if (key.startsWith('f_stop')) {
      return 'f/' + (Number.isInteger(value) ? value.toString() : value.toFixed(1));
    }
    if (key.startsWith('focal_length')) {
      return Math.round(value) + 'mm';
    }
    if (key.startsWith('iso')) {
      return 'ISO ' + Math.round(value).toLocaleString();
    }
    if (key.startsWith('face_ratio') || key.startsWith('luminance')) {
      return Math.round(value * 100) + '%';
    }
    if (key.startsWith('face_count')) {
      return Math.round(value).toString();
    }
    return '';
  }
}

/**
 * Formats modifier display values with appropriate units.
 * Bonus: +1.5 pts; Noise tolerance: percentage; Clipping multiplier: multiplier.
 */
@Pipe({ name: 'modifierValueFormat', standalone: true, pure: true })
export class ModifierValueFormatPipe implements PipeTransform {
  transform(value: number | null | undefined, key: string): string {
    if (value == null || isNaN(value)) return '';
    if (key === 'bonus') {
      const sign = value >= 0 ? '+' : '';
      return sign + value.toFixed(1) + ' pts';
    }
    if (key === 'noise_tolerance_multiplier') {
      return Math.round(value * 100) + '%';
    }
    if (key === '_clipping_multiplier') {
      return value.toFixed(1) + 'x';
    }
    return '';
  }
}
