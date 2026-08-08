export interface FolderItem {
  name: string;
  path: string;
  photo_count: number;
  cover_photo_path: string | null;
}

export interface FoldersResponse {
  folders: FolderItem[];
  has_direct_photos: boolean;
}

export interface FolderCrumb {
  name: string;
  path: string;
}

/**
 * Split a folder prefix into navigable breadcrumbs. Segments are accumulated rather than
 * filtered out so leading slashes survive — `/photos/2026/` must not become `photos/`,
 * which the API would match against nothing.
 */
export function buildFolderBreadcrumbs(prefix: string): FolderCrumb[] {
  if (!prefix) return [];
  const crumbs: FolderCrumb[] = [];
  let accumulated = '';
  for (const segment of prefix.replace(/\/+$/, '').split('/')) {
    accumulated += segment + '/';
    if (segment) crumbs.push({ name: segment, path: accumulated });
  }
  return crumbs;
}

/** Last segment of a folder prefix, for compact labels (chip, sidebar). */
export function folderDisplayName(prefix: string): string {
  return prefix.replace(/\/+$/, '').split('/').pop() || prefix;
}
