/**
 * The key two person names are compared by: outer spaces trimmed, then an
 * approximation of Python's ``str.casefold``, which the server compares with and
 * which is authoritative. Upper- then lower-casing folds "ß" to "ss" as casefold
 * does; it is locale-independent on purpose. This only decides what the client
 * pre-ticks, suggests or de-duplicates.
 */
export function personNameKey(name: string): string {
  return name.trim().toUpperCase().toLowerCase();
}

/** True when both names are set and match under {@link personNameKey}. */
export function sameName(a: string | null | undefined, b: string | null | undefined): boolean {
  return !!a?.trim() && !!b?.trim() && personNameKey(a) === personNameKey(b);
}

/** A name offered while typing one: the person that carries it, and its photo count. */
export interface PersonNameOption {
  id: number;
  name: string;
  count: number;
}

/**
 * One option per folded name from ``GET /api/filter_options/persons`` rows
 * (``[id, name, photo_count]``), keeping the person with the most photos, sorted by
 * name. Unnamed rows and ``excludeId`` are left out.
 */
export function personNameOptions(
  rows: readonly (readonly [number, string | null, number])[],
  excludeId: number | null = null,
): PersonNameOption[] {
  const byKey = new Map<string, PersonNameOption>();
  for (const [id, name, count] of rows) {
    const trimmed = name?.trim();
    if (!trimmed || id === excludeId) continue;
    const key = personNameKey(trimmed);
    const seen = byKey.get(key);
    if (!seen || count > seen.count) byKey.set(key, { id, name: trimmed, count });
  }
  return [...byKey.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Options whose folded name contains the folded ``query``, at most ``limit``; all of them for an empty query. */
export function matchPersonNames(
  options: readonly PersonNameOption[],
  query: string,
  limit = 50,
): PersonNameOption[] {
  const key = personNameKey(query);
  return (key ? options.filter((o) => personNameKey(o.name).includes(key)) : options).slice(0, limit);
}

/**
 * True when a person has no usable name: NULL, empty, or spaces only. Mirrors the
 * server's ``person_unnamed_clause`` (SQL ``TRIM`` strips spaces only, not tabs or
 * newlines), so the client and the API agree on which people still need naming.
 */
export function isUnnamedPerson(name: string | null | undefined): boolean {
  return (name ?? '').replace(/^ +| +$/g, '') === '';
}
