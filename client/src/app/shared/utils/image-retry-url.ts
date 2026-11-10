/** A deliberate rendition retry preserves the original query and skips offline storage. */
export function imageRetryUrl(source: string, nonce: string): string {
  const url = new URL(source, document.baseURI);
  url.searchParams.set('facet_retry', nonce);
  url.searchParams.set('ngsw-bypass', '1');
  return url.href;
}
