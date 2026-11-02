import type { Photo } from '../models/photo.model';

/** An album capability, never a substitute for the signed-in library session. */
export interface SharedAlbumMediaScope {
  readonly albumId: number;
  readonly token: string;
}

export function sharedAlbumMediaUrl(
  scope: SharedAlbumMediaScope,
  kind: 'thumbnail' | 'image' | 'download',
  assetId: string,
  size?: number,
  revision?: string | null,
): string {
  if (!Number.isSafeInteger(scope.albumId) || scope.albumId <= 0 || !scope.token) {
    throw new Error('Invalid shared album scope');
  }
  const params = new URLSearchParams({ asset_id: assetId, token: scope.token, 'ngsw-bypass': '1' });
  if (size) params.set('size', String(size));
  if (revision) params.set('preview', revision);
  return `/api/shared/album/${scope.albumId}/media/${kind}?${params}`;
}

/** Public wire identity is never a native path. Shared presentation components
 * reuse Photo's identity slot solely as this signed, album-bound handle. */
export type SharedAsset = Omit<Photo, 'path'> & { asset_id: string };
export function sharedAssetPhoto(asset: SharedAsset): Photo {
  if (!asset.asset_id || !/^-?(?:0|[1-9][0-9]{0,18})\.[0-9a-f]{64}$/.test(asset.asset_id)) {
    throw new Error('Invalid shared asset identity');
  }
  return { ...asset, path: asset.asset_id };
}
