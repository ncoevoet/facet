import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  FacesForPathPipe, IsEyesClosedPipe, WeightRemainingPipe,
  CullingGroup, CullingPhoto, CullingFace,
} from './burst-culling.pipes';

const photo = (overrides: Partial<CullingPhoto> = {}): CullingPhoto => ({
  path: '/p.jpg', filename: 'p.jpg', aggregate: 8, aesthetic: 8, tech_sharpness: 8,
  is_blink: 0, is_burst_lead: 0, date_taken: null, burst_score: 8, ...overrides,
});

const group = (overrides: Partial<CullingGroup> = {}): CullingGroup => ({
  group_id: 1, type: 'burst', reason: '', photos: [], best_path: '', count: 0, ...overrides,
});

describe('IsKeptPipe', () => {
  const pipe = new IsKeptPipe();

  it('returns true when path is in the kept set for the burst', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(true);
  });

  it('returns false when path is not in the kept set', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(false);
  });

  it('returns false when burst_id has no entry', () => {
    expect(pipe.transform('/photo1.jpg', new Map(), 99)).toBe(false);
  });
});

describe('IsDecidedPipe', () => {
  const pipe = new IsDecidedPipe();

  it('returns true when burst has selections and path is not kept', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(true);
  });

  it('returns false when path is kept', () => {
    const map = new Map<number, Set<string>>([[1, new Set(['/photo1.jpg'])]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });

  it('returns false when burst has no entry', () => {
    expect(pipe.transform('/photo1.jpg', new Map(), 1)).toBe(false);
  });

  it('returns false when kept set is empty', () => {
    const map = new Map<number, Set<string>>([[1, new Set<string>()]]);
    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });
});

describe('IsConfirmedPipe', () => {
  const pipe = new IsConfirmedPipe();

  it('returns true when group is confirmed', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Set(['1_burst']))).toBe(true);
  });

  it('returns false when group is not confirmed', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Set(['1_burst']))).toBe(false);
  });

  it('distinguishes between burst and similar types', () => {
    const confirmed = new Set(['1_burst']);
    expect(pipe.transform(group({ type: 'burst' }), confirmed)).toBe(true);
    expect(pipe.transform(group({ type: 'similar' }), confirmed)).toBe(false);
  });
});

describe('IsPassingPipe', () => {
  const pipe = new IsPassingPipe();

  it('returns true when group is in passingGroups', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Map([['1_burst', 4]]))).toBe(true);
  });

  it('returns false when group is not in passingGroups', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Map([['1_burst', 4]]))).toBe(false);
  });
});

describe('PassCountdownPipe', () => {
  const pipe = new PassCountdownPipe();

  it('returns the countdown value for a group in passingGroups', () => {
    expect(pipe.transform(group({ type: 'burst' }), new Map([['1_burst', 3]]))).toBe(3);
  });

  it('returns 0 for a group not in passingGroups', () => {
    expect(pipe.transform(group({ group_id: 2, type: 'similar' }), new Map([['1_burst', 3]]))).toBe(0);
  });
});

describe('FacesForPathPipe', () => {
  const pipe = new FacesForPathPipe();

  it('returns the faces for a known path', () => {
    const faces: CullingFace[] = [{ id: 1, face_index: 0 }];
    const map = new Map<string, CullingFace[]>([['/p.jpg', faces]]);
    expect(pipe.transform('/p.jpg', map)).toBe(faces);
  });

  it('returns an empty array for an unknown path', () => {
    expect(pipe.transform('/missing.jpg', new Map())).toEqual([]);
  });
});

describe('WeightRemainingPipe', () => {
  const pipe = new WeightRemainingPipe();

  it('returns remaining count against the configured threshold', () => {
    const stats = { category_breakdown: [{ category: 'portrait', count: 12 }], min_comparisons_for_optimization: 50 };
    expect(pipe.transform('portrait', stats)).toBe(38);
  });

  it('returns the full threshold when the category has no comparisons yet', () => {
    const stats = { category_breakdown: [{ category: 'street', count: 3 }], min_comparisons_for_optimization: 20 };
    expect(pipe.transform('portrait', stats)).toBe(20);
  });

  it('returns 0 (ready) once the threshold is met', () => {
    const stats = { category_breakdown: [{ category: 'portrait', count: 60 }], min_comparisons_for_optimization: 50 };
    expect(pipe.transform('portrait', stats)).toBe(0);
  });

  it('falls back to the default threshold of 50 when unset', () => {
    expect(pipe.transform('portrait', { category_breakdown: [] })).toBe(50);
  });

  it('returns 0 when category or stats are missing', () => {
    expect(pipe.transform(null, { min_comparisons_for_optimization: 50 })).toBe(0);
    expect(pipe.transform('portrait', null)).toBe(0);
  });
});

describe('IsEyesClosedPipe', () => {
  const pipe = new IsEyesClosedPipe();

  it('returns true when is_blink is set', () => {
    expect(pipe.transform(photo({ is_blink: 1 }))).toBe(true);
  });

  it('returns true when eyes_open_score is at or below the threshold', () => {
    expect(pipe.transform(photo({ eyes_open_score: 3 }))).toBe(true);
  });

  it('returns false when eyes are open and no blink', () => {
    expect(pipe.transform(photo({ eyes_open_score: 9 }))).toBe(false);
  });

  it('returns false when eyes_open_score is absent', () => {
    expect(pipe.transform(photo())).toBe(false);
  });
});
