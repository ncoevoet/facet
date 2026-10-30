import { Pipe, PipeTransform } from '@angular/core';

/** Facet's own features share one mark, told apart by colour. ✨ (`auto_awesome`) is
 *  kept for what an AI assistant made or picked, so it never reads as a score.
 *  Every ✦ sits beside its label or tooltip: colour is never the only cue. */
export const FEATURE_MARK = '✦';

export type MarkTone = 'quality' | 'taste' | 'moment' | 'memories' | 'smart';

const MARK_TONES: Readonly<Record<MarkTone, string>> = {
  quality: 'text-emerald-500',
  taste: 'text-amber-400',
  moment: 'text-[var(--mat-sys-primary)]',
  memories: 'text-rose-500',
  smart: 'text-teal-400',
};

/** Keys of the data-driven icon tables (sort options, weights, sidebar sections) that draw the mark. */
const MARKED_KEYS: Readonly<Record<string, MarkTone>> = {
  aesthetic: 'quality',
  aesthetic_percent: 'quality',
  'gallery.sidebar.moments': 'moment',
};

/** The colour class of a feature's ✦, by tone or by icon-table key; '' for anything unmarked. */
@Pipe({ name: 'markTone' })
export class MarkTonePipe implements PipeTransform {
  transform(toneOrKey: string | null | undefined): string {
    if (!toneOrKey) return '';
    return MARK_TONES[toneOrKey as MarkTone] ?? MARK_TONES[MARKED_KEYS[toneOrKey]] ?? '';
  }
}
