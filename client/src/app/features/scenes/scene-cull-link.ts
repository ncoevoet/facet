import { SceneDatePipe } from './scenes.pipes';

/** The capture window of one /scenes entry. */
export interface SceneWindow {
  start: string | null;
  end: string | null;
}

/** The /culling query string that culls exactly one scene. */
export interface SceneCullParams {
  group_by: 'scene';
  album: string | undefined;
  from: string | undefined;
  to: string | undefined;
  scene: string;
}

const SCENE_DATE = new SceneDatePipe();

/**
 * Built in one place for both ways into a scene cull: the "Cull this scene" button on /scenes,
 * and /culling moving on to the next scene once one is culled. Two copies would drift, and
 * the darkroom would then land on a URL that /scenes never opens.
 */
export function sceneCullParams(scene: SceneWindow, album: string | null): SceneCullParams {
  return {
    group_by: 'scene',
    album: album ?? undefined,
    from: scene.start ?? undefined,
    to: scene.end ?? undefined,
    scene: SCENE_DATE.transform(scene.start),
  };
}
