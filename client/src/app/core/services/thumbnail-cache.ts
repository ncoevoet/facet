/** Best-effort removal of thumbnail entries present during this cleanup.
 * In-flight requests can still refill the caches; this is not a complete privacy purge.
 */
export async function clearThumbnailCaches(paths?: readonly string[]): Promise<void> {
  if (!('caches' in globalThis)) return;
  const targets = paths ? new Set(paths) : null;
  if (targets && !targets.size) return;
  try {
    const names = await caches.keys();
    await Promise.allSettled(names.filter(name => name.includes(':thumbnails:')).map(async name => {
      const cache = await caches.open(name);
      const requests = await cache.keys();
      await Promise.allSettled(requests.filter(request => {
        if (!targets) return true;
        try {
          const url = new URL(request.url);
          return url.pathname.endsWith('/thumbnail') && targets.has(url.searchParams.get('path') ?? '');
        } catch { return false; }
      }).map(request => cache.delete(request)));
      // Keep the namespace attached: Angular retains these Cache objects and
      // may refill them. A later cleanup must still be able to reach them.
    }));
  } catch { /* Storage may be unavailable; logout/catalog removal must still complete. */ }
}
