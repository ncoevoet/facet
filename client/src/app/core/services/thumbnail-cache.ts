/** Best-effort removal of thumbnail entries present during this cleanup.
 * In-flight requests can still refill the caches; this is not a complete privacy purge.
 */
export async function clearThumbnailCaches(): Promise<void> {
  if (!('caches' in globalThis)) return;
  try {
    const names = await caches.keys();
    await Promise.allSettled(names.filter(name => name.includes(':thumbnails:')).map(async name => {
      const cache = await caches.open(name);
      const requests = await cache.keys();
      await Promise.allSettled(requests.map(request => cache.delete(request)));
      // Keep the namespace attached: Angular retains these Cache objects and
      // may refill them. A later cleanup must still be able to reach them.
    }));
  } catch { /* Storage may be unavailable; logout/catalog removal must still complete. */ }
}
