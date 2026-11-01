/** An album capability, never a substitute for the signed-in library session. */
export interface SharedAlbumMediaScope {
  readonly albumId: number;
  readonly token: string;
}

export function sharedAlbumMediaUrl(
  scope: SharedAlbumMediaScope,
  kind: 'thumbnail' | 'image' | 'download',
  path: string,
  size?: number,
  revision?: string | null,
): string {
  if (!Number.isSafeInteger(scope.albumId) || scope.albumId <= 0 || !scope.token) {
    throw new Error('Invalid shared album scope');
  }
  const params = new URLSearchParams({ path, token: scope.token, 'ngsw-bypass': '1' });
  if (size) params.set('size', String(size));
  if (revision) params.set('preview', revision);
  return `/api/shared/album/${scope.albumId}/media/${kind}?${params}`;
}
