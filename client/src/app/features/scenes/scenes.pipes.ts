import { Pipe, PipeTransform } from '@angular/core';

/** Format an EXIF "YYYY:MM:DD HH:MM:SS" timestamp as "DD/MM/YYYY HH:MM". */
@Pipe({ name: 'sceneDate' })
export class SceneDatePipe implements PipeTransform {
  transform(value: string | null): string {
    if (!value) return '';
    const m = value.match(/^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2})/);
    if (!m) return value;
    const [, y, mo, d, h, min] = m;
    return `${d}/${mo}/${y} ${h}:${min}`;
  }
}

/** Prettify a narrative-moment key ("first_dance") into a label ("First Dance"). */
@Pipe({ name: 'momentLabel' })
export class MomentLabelPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value || value === 'other') return '';
    return value.split('_').map(w => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');
  }
}

/**
 * True when a moment label is below the confidence threshold and should be
 * shown dimmed + "(uncertain)". The F21 forward-backward posterior is a true
 * [0,1] confidence (``other`` frames sit at the neutral 0.5 but never carry a
 * label), so a single threshold separates confident from ambiguous frames. A
 * threshold of 0 (the default) never dims anything.
 */
@Pipe({ name: 'momentUncertain' })
export class MomentUncertainPipe implements PipeTransform {
  transform(confidence: number | null | undefined, threshold: number | null | undefined): boolean {
    if (confidence == null || !threshold || threshold <= 0) return false;
    return confidence < threshold;
  }
}
