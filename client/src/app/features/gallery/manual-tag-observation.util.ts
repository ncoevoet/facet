import type { Photo } from '../../shared/models/photo.model';

export interface ManualTagObservation {
  photos: number;
  tags: { tag: string; count: number }[];
  overflow: number;
}

export function observeManualTags(photos: Partial<Pick<Photo, 'manual_tags'>>[]): ManualTagObservation {
  const counts = new Map<string, number>();
  for (const photo of photos) {
    for (const tag of new Set(photo.manual_tags ?? [])) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  const tags = [...counts].map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
  return { photos: photos.length, tags: tags.slice(0, 20), overflow: Math.max(0, tags.length - 20) };
}
