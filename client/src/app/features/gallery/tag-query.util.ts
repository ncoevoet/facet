export const TAG_QUERY_LIMIT = 50;
export const TAG_QUERY_NAME_LIMIT = 200;
export const TAG_QUERY_GROUPS = ['any', 'all', 'none'] as const;
export type TagQueryGroup = typeof TAG_QUERY_GROUPS[number];
export type TagQuery = Record<TagQueryGroup, string[]>;

/** JSON.parse alone accepts duplicate keys, which could drop an intended group.
 * Values below are arrays, so only depth-one strings can be property names. */
function hasDuplicateKeys(raw: string): boolean {
  const keys = new Set<string>();
  let depth = 0;
  for (let index = 0; index < raw.length; index++) {
    const ch = raw[index];
    if (ch === '"') {
      const start = index;
      for (index++; index < raw.length; index++) {
        if (raw[index] === '\\') index++;
        else if (raw[index] === '"') break;
      }
      if (depth === 1) {
        const key = JSON.parse(raw.slice(start, index + 1)) as string;
        if (keys.has(key)) return true;
        keys.add(key);
      }
    } else if (ch === '{' || ch === '[') depth++;
    else if (ch === '}' || ch === ']') depth--;
  }
  return false;
}

export function parseTagQuery(raw: string): TagQuery | null {
  const result: TagQuery = { any: [], all: [], none: [] };
  if (raw === '') return result;
  try {
    if (Array.from(raw).length > 20000) return null;
    const groups: unknown = JSON.parse(raw);
    if (!groups || typeof groups !== 'object' || Array.isArray(groups)) return null;
    let count = 0;
    for (const [key, names] of Object.entries(groups)) {
      if (!(TAG_QUERY_GROUPS as readonly string[]).includes(key) || !Array.isArray(names)) return null;
      count += names.length;
      if (count > TAG_QUERY_LIMIT || names.some(name => typeof name !== 'string' || !name.trim()
        || Array.from(name).length > TAG_QUERY_NAME_LIMIT || /[\p{Cc}\p{Cs}]/u.test(name))) return null;
      result[key as TagQueryGroup] = [...new Set(names as string[])];
    }
    return hasDuplicateKeys(raw) ? null : result;
  } catch { return null; }
}

export function serializeTagQuery(groups: TagQuery): string {
  const entries = TAG_QUERY_GROUPS.filter(key => groups[key].length).map(key => [key, groups[key]]);
  return entries.length ? JSON.stringify(Object.fromEntries(entries)) : '';
}

export function hasTagQuery(raw: string): boolean {
  const groups = parseTagQuery(raw);
  return groups === null || TAG_QUERY_GROUPS.some(key => groups[key].length > 0);
}
