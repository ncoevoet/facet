import {
  FACE_BOX_MODE_KEY, nextFaceBoxMode, readFaceBoxMode, writeFaceBoxMode,
  FACE_BOX_MODE_ICONS, FACE_BOX_MODE_LABELS,
} from './face-box-mode';

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    get length() { return data.size; },
    clear: () => data.clear(),
    getItem: (k: string) => data.get(k) ?? null,
    key: (i: number) => [...data.keys()][i] ?? null,
    removeItem: (k: string) => { data.delete(k); },
    setItem: (k: string, v: string) => { data.set(k, v); },
  };
}

describe('face box mode', () => {
  it('cycles hover, always, off, then hover again', () => {
    expect(nextFaceBoxMode('hover')).toBe('always');
    expect(nextFaceBoxMode('always')).toBe('off');
    expect(nextFaceBoxMode('off')).toBe('hover');
  });

  it('defaults to hover', () => {
    expect(readFaceBoxMode(memoryStorage())).toBe('hover');
    expect(readFaceBoxMode(null)).toBe('hover');
  });

  it('remembers the chosen mode', () => {
    const storage = memoryStorage();
    writeFaceBoxMode('off', storage);
    expect(storage.getItem(FACE_BOX_MODE_KEY)).toBe('off');
    expect(readFaceBoxMode(storage)).toBe('off');
  });

  it('gives each mode its own icon and label', () => {
    expect(new Set(Object.values(FACE_BOX_MODE_ICONS)).size).toBe(3);
    expect(FACE_BOX_MODE_LABELS).toEqual({
      off: 'photo_faces.box_mode_off', hover: 'photo_faces.box_mode_hover', always: 'photo_faces.box_mode_always',
    });
  });
});
