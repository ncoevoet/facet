const MAX_ERROR_DETAIL_LENGTH = 300;

/**
 * Pull a human-readable `detail`/`message` string out of an HTTP error body.
 * FastAPI validation errors put a list of objects in `detail`, so anything
 * non-string is dropped rather than rendered, and the result is capped so a
 * pathological server message cannot blow out a toast or dialog layout.
 */
export function extractErrorDetail(error: unknown): string | undefined {
  const body = (error as { error?: unknown } | null | undefined)?.error;
  if (!body || typeof body !== 'object') return undefined;
  const record = body as Record<string, unknown>;
  const raw = typeof record['detail'] === 'string' ? record['detail']
    : typeof record['message'] === 'string' ? record['message']
    : undefined;
  if (!raw) return undefined;
  return raw.length > MAX_ERROR_DETAIL_LENGTH ? `${raw.slice(0, MAX_ERROR_DETAIL_LENGTH)}…` : raw;
}
