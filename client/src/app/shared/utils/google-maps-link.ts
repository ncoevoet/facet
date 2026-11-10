/**
 * Read a latitude/longitude pair out of what a user copies from Google Maps.
 *
 * Mirrors `utils/google_maps_link.py` (same rules, same order) so a short link the
 * server resolves lands on the point this would have read from the long URL.
 *
 * A URL is read in this order of preference:
 *  1. `!3dLAT!4dLON` in the `data=` blob: the dropped pin / place itself;
 *  2. `q=` / `query=` / `ll=` / `center=` / `destination=` query values;
 *  3. `@LAT,LON[,ZOOMz]`: the viewport centre;
 *  4. a `/maps/search/...` or `/maps/place/...` path segment that is itself a pair.
 * Free text may be a decimal pair (`32.6064, -116.3239` or `32.6064 -116.3239`)
 * or degrees/minutes/seconds (`32°36'23.0"N 116°19'26.0"W`). Every result is
 * range-checked.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

export const MAPS_LINK_MAX_INPUT = 2048;

/** Hosts whose links the viewer may follow server-side (`POST /api/geo/resolve_maps_link`). */
export const RESOLVABLE_MAPS_HOSTS: readonly string[] = ['maps.app.goo.gl', 'goo.gl', 'maps.google.com', 'www.google.com', 'google.com'];

const NUM = String.raw`[-+]?\d{1,3}(?:\.\d+)?`;
const DECIMAL_PAIR = new RegExp(String.raw`^\s*(${NUM})\s*(?:,|;|\s)\s*(${NUM})\s*$`);
const DMS_PART = String.raw`(\d{1,3}(?:\.\d+)?)\s*°\s*(?:(\d{1,2}(?:\.\d+)?)\s*['′’]\s*)?(?:(\d{1,2}(?:\.\d+)?)\s*(?:"|″|”|''|′′)\s*)?([NSEWnsew])`;
const DMS_PAIR = new RegExp(String.raw`^\s*${DMS_PART}\s*,?\s*${DMS_PART}\s*$`);
const PIN = new RegExp(String.raw`!3d(${NUM})!4d(${NUM})`, 'g');
const AT = new RegExp(String.raw`@(${NUM}),(${NUM})`);
const QUERY_KEYS = ['q', 'query', 'll', 'center', 'destination'] as const;
const PATH = /\/maps\/(?:search|place)\/([^/@]+)/;

function valid(lat: number, lng: number): LatLng | null {
  return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { lat, lng } : null;
}

function dmsValue(deg: string, minutes: string | undefined, seconds: string | undefined, hemi: string): number | null {
  const d = Number(deg), m = minutes ? Number(minutes) : 0, s = seconds ? Number(seconds) : 0;
  if (m >= 60 || s >= 60 || ((minutes || seconds) && !Number.isInteger(d))) return null;
  const value = d + m / 60 + s / 3600;
  return 'SW'.includes(hemi.toUpperCase()) ? -value : value;
}

/** A free-text coordinate pair, decimal or DMS; `null` if it is neither. */
export function parseCoordinatePair(text: string): LatLng | null {
  if (typeof text !== 'string' || text.length > MAPS_LINK_MAX_INPUT) return null;
  let match = DECIMAL_PAIR.exec(text);
  if (match) return valid(Number(match[1]), Number(match[2]));
  match = DMS_PAIR.exec(text);
  if (!match) return null;
  const g = match.slice(1);
  const first = g[3].toUpperCase(), second = g[7].toUpperCase();
  let lat: number | null, lng: number | null;
  if ('NS'.includes(first) && 'EW'.includes(second)) {
    lat = dmsValue(g[0], g[1], g[2], g[3]); lng = dmsValue(g[4], g[5], g[6], g[7]);
  } else if ('EW'.includes(first) && 'NS'.includes(second)) {
    lng = dmsValue(g[0], g[1], g[2], g[3]); lat = dmsValue(g[4], g[5], g[6], g[7]);
  } else return null;
  return lat === null || lng === null ? null : valid(lat, lng);
}

/** Per escape run, as `urllib.parse.unquote` does: one stray `%` must not keep the rest encoded. */
function safeDecode(value: string): string {
  return value.replace(/(?:%[0-9A-Fa-f]{2})+/g, run => {
    try { return decodeURIComponent(run); } catch { return run; }
  });
}

function queryValues(query: string): Map<string, string> {
  const values = new Map<string, string>();
  for (const part of query.replace(/^\?/, '').split('&')) {
    if (!part) continue;
    const eq = part.indexOf('=');
    const key = safeDecode((eq < 0 ? part : part.slice(0, eq)).replace(/\+/g, ' '));
    // A repeated key keeps its last value, as `dict(parse_qsl(...))` does server-side.
    values.set(key, safeDecode((eq < 0 ? '' : part.slice(eq + 1)).replace(/\+/g, ' ')));
  }
  return values;
}

function queryOf(url: string): string {
  const noFragment = url.split('#', 1)[0];
  const at = noFragment.indexOf('?');
  return at < 0 ? '' : noFragment.slice(at + 1);
}

/** Coordinates a Google Maps URL carries, by the preference order above. */
export function parseMapsUrl(url: string): LatLng | null {
  if (typeof url !== 'string' || url.length > MAPS_LINK_MAX_INPUT) return null;
  // Decoded twice: a consent page wraps the maps URL in `continue=`.
  const decoded = safeDecode(safeDecode(url));
  const pins = [...decoded.matchAll(PIN)];
  if (pins.length) {
    const last = pins[pins.length - 1];
    return valid(Number(last[1]), Number(last[2]));
  }
  const queries = [queryOf(url)];
  for (const value of queryValues(queries[0]).values()) {
    if (/^https?:\/\//.test(value)) queries.push(queryOf(value));
  }
  for (const query of queries) {
    const params = queryValues(query);
    for (const key of QUERY_KEYS) {
      const value = params.get(key);
      if (!value) continue;
      const pair = parseCoordinatePair(value.replace(/^loc:/, '').trim());
      if (pair) return pair;
    }
  }
  const at = AT.exec(decoded);
  if (at) return valid(Number(at[1]), Number(at[2]));
  const path = PATH.exec(decoded);
  return path ? parseCoordinatePair(path[1].replace(/\+/g, ' ')) : null;
}

/** Whatever the user pasted: a URL or a free-text pair. */
export function parseGoogleMapsInput(text: string): LatLng | null {
  if (typeof text !== 'string' || text.length > MAPS_LINK_MAX_INPUT) return null;
  const stripped = text.trim();
  return /^https?:\/\//i.test(stripped) ? parseMapsUrl(stripped) : parseCoordinatePair(stripped);
}

/** A link only the server can follow: http(s), an allowed host, no credentials or port. */
export function isResolvableMapsLink(text: string): boolean {
  if (typeof text !== 'string' || text.length > MAPS_LINK_MAX_INPUT) return false;
  let url: URL;
  try { url = new URL(text.trim()); } catch { return false; }
  return (url.protocol === 'https:' || url.protocol === 'http:') && RESOLVABLE_MAPS_HOSTS.includes(url.hostname)
    && !url.username && !url.password && (url.port === '' || url.port === '443');
}

/** Google Maps opened on a point, in a new tab (no API, no key). */
export function googleMapsSearchUrl(point: LatLng): string {
  return `https://www.google.com/maps/search/?api=1&query=${point.lat.toFixed(6)},${point.lng.toFixed(6)}`;
}
