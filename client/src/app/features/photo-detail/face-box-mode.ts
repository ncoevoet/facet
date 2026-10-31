import { I18N } from '../../core/i18n/keys';

/**
 * How the photo page draws face boxes: ``off`` draws none and makes the face layer
 * inert, ``hover`` shows them under the pointer or keyboard focus, ``always`` keeps
 * them shown.
 */
export type FaceBoxMode = 'off' | 'hover' | 'always';

/** The toolbar button's cycle, starting from the default. */
export const FACE_BOX_MODES: readonly FaceBoxMode[] = ['hover', 'always', 'off'];

export const FACE_BOX_MODE_KEY = 'facet_face_box_mode';

/** The mode after ``mode`` in the cycle. */
export function nextFaceBoxMode(mode: FaceBoxMode): FaceBoxMode {
  return FACE_BOX_MODES[(FACE_BOX_MODES.indexOf(mode) + 1) % FACE_BOX_MODES.length];
}

/** Icon per mode (classic Material Icons ligatures, as the project's font ships). */
export const FACE_BOX_MODE_ICONS: Record<FaceBoxMode, string> = {
  off: 'face_retouching_off',
  hover: 'crop_free',
  always: 'face',
};

/** Tooltip and label per mode, naming it and what a click switches to. */
export const FACE_BOX_MODE_LABELS: Record<FaceBoxMode, string> = {
  off: I18N.photo_faces.box_mode_off,
  hover: I18N.photo_faces.box_mode_hover,
  always: I18N.photo_faces.box_mode_always,
};

/** The mode remembered by this browser, ``hover`` when none is stored. */
export function readFaceBoxMode(storage: Storage | null = safeStorage()): FaceBoxMode {
  if (!storage) return 'hover';
  try {
    const stored = storage.getItem(FACE_BOX_MODE_KEY);
    if (stored === 'off' || stored === 'hover' || stored === 'always') return stored;
    return 'hover';
  } catch {
    return 'hover';
  }
}

export function writeFaceBoxMode(mode: FaceBoxMode, storage: Storage | null = safeStorage()): void {
  try {
    storage?.setItem(FACE_BOX_MODE_KEY, mode);
  } catch {
    // private window or blocked storage: the choice lasts for this page only
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
