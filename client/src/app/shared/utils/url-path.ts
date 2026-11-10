/** The path of a router URL: everything before the query string or fragment. */
export function pathOf(url: string): string {
  return url.split('?')[0].split('#')[0];
}

/** A local gallery collection, optionally carrying query or fragment state. */
export function isGalleryCollectionUrl(url: string): boolean {
  return /^\/(?:album\/\d+)?$/.test(pathOf(url));
}
