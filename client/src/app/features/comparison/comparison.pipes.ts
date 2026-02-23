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
