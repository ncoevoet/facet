import { Pipe, PipeTransform } from '@angular/core';

/** True when a photo is marked for rejection within a scene. */
@Pipe({ name: 'sceneRejected' })
export class SceneRejectedPipe implements PipeTransform {
  transform(rejectedMap: Map<number, Set<string>>, sceneId: number, path: string): boolean {
    return rejectedMap.get(sceneId)?.has(path) ?? false;
  }
}

/** Number of photos marked for rejection in a scene (for the cull-button label). */
@Pipe({ name: 'sceneRejectCount' })
export class SceneRejectCountPipe implements PipeTransform {
  transform(rejectedMap: Map<number, Set<string>>, sceneId: number): number {
    return rejectedMap.get(sceneId)?.size ?? 0;
  }
}

/** Format an EXIF "YYYY:MM:DD HH:MM:SS" timestamp as "DD/MM/YYYY HH:MM". */
@Pipe({ name: 'sceneDate' })
export class SceneDatePipe implements PipeTransform {
  transform(value: string | null): string {
    if (!value) return '';
    const m = value.match(/^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2})/);
    if (!m) return value;
    const [, y, mo, d, h, min] = m;
    return `${d}/${mo}/${y} ${h}:${min}`;
  }
}
