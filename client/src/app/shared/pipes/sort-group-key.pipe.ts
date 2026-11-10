import { Pipe, PipeTransform } from '@angular/core';

const sortGroupKey = (groupName: string): string => groupName.toLowerCase().replace(/\s+/g, '_');

/** Icon of each sort group's submenu entry, keyed by the group's i18n key. */
export const SORT_GROUP_ICONS: Readonly<Record<string, string>> = {
  general: 'leaderboard', face_metrics: 'portrait', technical: 'deblur', color: 'palette', exposure: 'exposure',
  composition: 'grid_on', subject_saliency: 'center_focus_strong', content: 'auto_stories', camera: 'camera',
};

@Pipe({ name: 'sortGroupKey', standalone: true, pure: true })
export class SortGroupKeyPipe implements PipeTransform {
  transform(groupName: string): string {
    return sortGroupKey(groupName);
  }
}

@Pipe({ name: 'sortGroupIcon', standalone: true, pure: true })
export class SortGroupIconPipe implements PipeTransform {
  transform(groupName: string): string {
    return SORT_GROUP_ICONS[sortGroupKey(groupName)] ?? 'sort';
  }
}
