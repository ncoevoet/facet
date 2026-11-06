import { i18nKeys } from '../../core/i18n/keys';

/** Sorts reachable outside the `sort_options` table (search relevance, learned and computed scores, filename). */
const SORT_LABELS_OUTSIDE_OPTIONS = (): Readonly<Record<string, string>> => {
  const keys = i18nKeys();
  return {
    relevance: keys.gallery.sort_relevance,
    learned_score: keys.gallery.sort_my_taste,
    top_picks_score: keys.photo_types.top_picks,
    filename: keys.filter_labels.search,
  };
};

/** Translation key naming a gallery sort column. */
export function sortLabelKey(sort: string): string {
  const outside = SORT_LABELS_OUTSIDE_OPTIONS();
  return Object.hasOwn(outside, sort) ? outside[sort] : `sort_options.${sort}`;
}
