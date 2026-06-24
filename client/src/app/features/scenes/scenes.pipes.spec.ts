import { SceneRejectedPipe, SceneRejectCountPipe, SceneDatePipe } from './scenes.pipes';

describe('SceneRejectedPipe', () => {
  const pipe = new SceneRejectedPipe();

  it('returns true when the path is rejected in that scene', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/a.jpg'])]]);
    expect(pipe.transform(map, 1, '/a.jpg')).toBe(true);
  });

  it('returns false when the path is not rejected', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/a.jpg'])]]);
    expect(pipe.transform(map, 1, '/b.jpg')).toBe(false);
  });

  it('returns false when the scene has no entry', () => {
    expect(pipe.transform(new Map(), 9, '/a.jpg')).toBe(false);
  });
});

describe('SceneRejectCountPipe', () => {
  const pipe = new SceneRejectCountPipe();

  it('counts rejected paths in a scene', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/a.jpg', '/b.jpg'])]]);
    expect(pipe.transform(map, 1)).toBe(2);
  });

  it('returns 0 for an unknown scene', () => {
    expect(pipe.transform(new Map(), 5)).toBe(0);
  });
});

describe('SceneDatePipe', () => {
  const pipe = new SceneDatePipe();

  it('reformats an EXIF timestamp to DD/MM/YYYY HH:MM', () => {
    expect(pipe.transform('2024:06:15 10:05:00')).toBe('15/06/2024 10:05');
  });

  it('handles ISO-style separators', () => {
    expect(pipe.transform('2024-06-15T10:05:00')).toBe('15/06/2024 10:05');
  });

  it('returns empty string for null', () => {
    expect(pipe.transform(null)).toBe('');
  });

  it('passes through an unparseable value', () => {
    expect(pipe.transform('not-a-date')).toBe('not-a-date');
  });
});
