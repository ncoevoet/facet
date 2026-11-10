import registry from './score-presence.generated.json';

export type ScorePresenceMode = 'include_missing' | 'missing_only' | 'measured_only';
export type ScorePresence = Record<string, ScorePresenceMode>;
export const SCORE_PRESENCE_KEYS: ReadonlySet<string> = new Set(registry.keys);

export function parseScorePresence(raw: string): ScorePresence | null {
  if (raw === '') return {};
  try {
    if (typeof raw !== 'string' || raw.length > 5000) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const entries = Object.entries(value);
    if (entries.some(([key, mode]) => !SCORE_PRESENCE_KEYS.has(key) || !registry.modes.includes(mode))) return null;
    // All accepted values are fixed strings, so property-token counting also
    // rejects duplicate keys, including alternate Unicode escape spellings.
    if ((raw.match(/"(?:[^"\\]|\\.)*"\s*:/g) ?? []).length !== entries.length) return null;
    return value as ScorePresence;
  } catch { return null; }
}

export function serializeScorePresence(value: ScorePresence): string {
  const keys = Object.keys(value).sort();
  return keys.length ? JSON.stringify(Object.fromEntries(keys.map(key => [key, value[key]]))) : '';
}
