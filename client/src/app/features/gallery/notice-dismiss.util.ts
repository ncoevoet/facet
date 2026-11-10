/** The gallery's floating notices the user closed in this browser tab, keyed by kind,
 *  each holding the signatures the notice had when it was closed (the last
 *  `MAX_DISMISSALS_PER_KIND`, oldest first). A notice whose current signature is not
 *  among them (another scope, another count) is a different notice and shows; going
 *  back to a scope closed earlier finds it still closed. Kept in sessionStorage: a
 *  reload keeps it closed, a new tab starts clean, and closing never changes anything else. */
export const NOTICE_DISMISSALS_KEY = 'facet_notice_dismissals';
export const MAX_DISMISSALS_PER_KIND = 20;

export type NoticeKind = 'review_progress' | 'review_bookmark' | 'hidden' | 'restore_hidden' | 'render_migration';

export type NoticeDismissals = Partial<Record<NoticeKind, string[]>>;

export function readNoticeDismissals(): NoticeDismissals {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(NOTICE_DISMISSALS_KEY) ?? '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const dismissals: NoticeDismissals = {};
    for (const [kind, signatures] of Object.entries(value)) {
      if (Array.isArray(signatures)) dismissals[kind as NoticeKind] = signatures.filter(s => typeof s === 'string');
    }
    return dismissals;
  } catch {
    return {};
  }
}

/** The record with `signature` closed for `kind`, the oldest dropped past the cap. */
export function withDismissal(dismissals: NoticeDismissals, kind: NoticeKind, signature: string): NoticeDismissals {
  const kept = (dismissals[kind] ?? []).filter(s => s !== signature);
  return { ...dismissals, [kind]: [...kept, signature].slice(-MAX_DISMISSALS_PER_KIND) };
}

export function saveNoticeDismissals(dismissals: NoticeDismissals): void {
  try {
    sessionStorage.setItem(NOTICE_DISMISSALS_KEY, JSON.stringify(dismissals));
  } catch { /* Storage denied/full: the close still holds until reload. */ }
}
