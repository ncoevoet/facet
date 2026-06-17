import { ScoreClassPipe, SortScorePipe } from './score.pipes';
import { Photo } from '../models/photo.model';

describe('ScoreClassPipe', () => {
  const pipe = new ScoreClassPipe();

  describe('without config thresholds (null / no quality_thresholds)', () => {
    it('returns green for score >= 8', () => {
      expect(pipe.transform(8, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(10, null)).toBe('bg-green-600 text-white');
    });

    it('returns yellow for 6 <= score < 8', () => {
      expect(pipe.transform(6, null)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(7.9, null)).toBe('bg-yellow-600 text-white');
    });

    it('returns orange for 4 <= score < 6', () => {
      expect(pipe.transform(4, null)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(5.99, null)).toBe('bg-orange-600 text-white');
    });

    it('returns red for score < 4', () => {
      expect(pipe.transform(3.99, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(0, null)).toBe('bg-red-600 text-white');
    });

    it('returns red for negative scores', () => {
      expect(pipe.transform(-5, null)).toBe('bg-red-600 text-white');
    });

    it('falls back to default thresholds when config has no quality_thresholds', () => {
      expect(pipe.transform(8, {})).toBe('bg-green-600 text-white');
      expect(pipe.transform(3, {})).toBe('bg-red-600 text-white');
    });
  });

  describe('with config quality_thresholds', () => {
    const config = { quality_thresholds: { excellent: 9, great: 7, good: 5 } };

    it('returns green at or above the excellent threshold', () => {
      expect(pipe.transform(9, config)).toBe('bg-green-600 text-white');
      expect(pipe.transform(9.5, config)).toBe('bg-green-600 text-white');
    });

    it('returns yellow between great and excellent', () => {
      expect(pipe.transform(7, config)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(8.99, config)).toBe('bg-yellow-600 text-white');
    });

    it('returns orange between good and great', () => {
      expect(pipe.transform(5, config)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(6.99, config)).toBe('bg-orange-600 text-white');
    });

    it('returns red below the good threshold', () => {
      expect(pipe.transform(4.99, config)).toBe('bg-red-600 text-white');
      expect(pipe.transform(0, config)).toBe('bg-red-600 text-white');
    });
  });
});

describe('SortScorePipe', () => {
  const pipe = new SortScorePipe();

  // Minimal Photo stub — only the fields exercised by the tests matter.
  function makePhoto(overrides: Partial<Photo>): Photo {
    return { aggregate: 5, aesthetic: 7, ...overrides } as Photo;
  }

  it('returns the numeric value of the requested sort column', () => {
    const photo = makePhoto({ aggregate: 5, aesthetic: 8.2 });
    expect(pipe.transform(photo, 'aesthetic')).toBe(8.2);
  });

  it('returns aggregate when the sort column does not exist', () => {
    const photo = makePhoto({ aggregate: 4.4 });
    expect(pipe.transform(photo, 'nonexistent_column')).toBe(4.4);
  });

  it('falls back to aggregate when the sort column value is null', () => {
    const photo = makePhoto({ aggregate: 6.1, face_quality: null });
    expect(pipe.transform(photo, 'face_quality')).toBe(6.1);
  });

  it('falls back to aggregate when the sort column value is a string', () => {
    const photo = makePhoto({ aggregate: 3.3, camera_model: 'Canon R7' });
    expect(pipe.transform(photo, 'camera_model')).toBe(3.3);
  });

  it('returns zero when the requested column is numerically zero (not falling back)', () => {
    const photo = makePhoto({ aggregate: 9, face_count: 0 });
    expect(pipe.transform(photo, 'face_count')).toBe(0);
  });

  it('returns aggregate itself when sorting by aggregate', () => {
    const photo = makePhoto({ aggregate: 7.7 });
    expect(pipe.transform(photo, 'aggregate')).toBe(7.7);
  });

  it('returns negative numeric values as-is', () => {
    const photo = makePhoto({ aggregate: 2, isolation_bonus: -1.5 });
    expect(pipe.transform(photo, 'isolation_bonus')).toBe(-1.5);
  });
});
