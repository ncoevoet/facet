import { DEFAULT_FILTERS, GalleryFilters } from './gallery-filters.util';

const STORAGE_KEY = 'facet_review_queues_v1';
const MAX_USERS = 20;
const MAX_BYTES = 16000;
const EPHEMERAL = new Set(['page', 'sequence_group_id', 'sequence_kind', 'burst_group_id', 'duplicate_group_id']);

/** A queue bookmark, never a second copy of review decisions or a photo cursor. */
export interface ReviewQueue {
  filters: GalleryFilters;
}

function canonicalFilters(value: unknown): GalleryFilters | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  // Scanner-assigned groups can name different photos after a rescan. Keep the last stable queue instead.
  if ([...EPHEMERAL].some(key => key !== 'page' && source[key])) return null;
  const filters = { ...DEFAULT_FILTERS };
  for (const key of Object.keys(DEFAULT_FILTERS) as (keyof GalleryFilters)[]) {
    const item = source[key];
    if (item === undefined || EPHEMERAL.has(key)) continue;
    if (typeof item !== typeof DEFAULT_FILTERS[key] || (typeof item === 'string' && item.length > 2048)
      || (typeof item === 'number' && !Number.isFinite(item))) return null;
    Object.assign(filters, { [key]: item });
  }
  if (filters.review_status !== 'undecided' || filters.similar_to || filters.semanticQuery
    || filters.per_page < 1 || filters.per_page > 500
    || (filters.album_id && filters.album_id !== '0' && !/^[1-9]\d*$/.test(filters.album_id))) return null;
  if (filters.album_id === '0') filters.album_id = '';
  filters.page = 1;
  return filters;
}

function readEntries(): [string, ReviewQueue][] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw || raw.length > MAX_BYTES * MAX_USERS) return [];
    const entries: unknown = JSON.parse(raw);
    if (!Array.isArray(entries)) return [];
    return entries.slice(-MAX_USERS).flatMap(entry => {
      if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string' || entry[0].length > 256) return [];
      const filters = canonicalFilters(entry[1]?.filters);
      return filters ? [[entry[0], { filters }] as [string, ReviewQueue]] : [];
    });
  } catch { return []; }
}

export function readReviewQueue(identity: string): ReviewQueue | null {
  return readEntries().find(([key]) => key === identity)?.[1] ?? null;
}

export function saveReviewQueue(identity: string, filters: GalleryFilters): void {
  const canonical = canonicalFilters(filters);
  if (!canonical || identity.length > 256) return;
  const queue = { filters: canonical };
  if (JSON.stringify(queue).length > MAX_BYTES) return;
  const entries = [...readEntries().filter(([key]) => key !== identity), [identity, queue]].slice(-MAX_USERS);
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(entries)); } catch { /* Storage denied/full: reviewing still works. */ }
}
