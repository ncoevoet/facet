import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  FacesForPathPipe, FacePoorExpressionPipe, FaceRingClassPipe, FaceDimmedPipe,
  WeightRemainingPipe, SortIconPipe, CategoryIconPipe, CullProfileIconPipe,
  CullPreviewUrlPipe, SubjectForPathPipe, SubjectRingClassPipe,
  CullingGroup, CullingFace, CullingSubject, FaceThresholds,
} from './burst-culling.pipes';

const subject = (overrides: Partial<CullingSubject> = {}): CullingSubject => ({
  path: '/p.jpg', has_subject: true, crop: 'data:image/jpeg;base64,x',
  subject_sharpness: null, subject_prominence: null,
  crop_sharpness: 100, crop_sharpness_score: 10, ...overrides,
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

describe('SubjectForPathPipe', () => {
  const pipe = new SubjectForPathPipe();

  it('returns the subject for a known path', () => {
    const s = subject();
    const map = new Map<string, CullingSubject>([['/p.jpg', s]]);
    expect(pipe.transform('/p.jpg', map)).toBe(s);
  });

  it('returns null for an unknown path', () => {
    expect(pipe.transform('/missing.jpg', new Map())).toBeNull();
  });
});

describe('SubjectRingClassPipe', () => {
  const pipe = new SubjectRingClassPipe();

  it('rings the sharpest tier green', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 10 }))).toBe('ring-green-500');
  });

  it('rings the mid tier amber', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 6 }))).toBe('ring-amber-500');
  });

  it('rings the softest tier red', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: 2 }))).toBe('ring-red-500');
  });

  it('is neutral when no score is available', () => {
    expect(pipe.transform(subject({ crop_sharpness_score: null }))).toBe('ring-white/20');
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

const face = (overrides: Partial<CullingFace> = {}): CullingFace =>
  ({ id: 1, face_index: 0, ...overrides });

const thresholds: FaceThresholds = { eyes_closed_max: 4.0, poor_expression_min: 4.0 };

describe('FacePoorExpressionPipe', () => {
  const pipe = new FacePoorExpressionPipe();

  it('returns true when expression_score is below the server threshold', () => {
    expect(pipe.transform(face({ expression_score: 2 }), thresholds)).toBe(true);
  });

  it('returns false when expression_score is at or above the threshold', () => {
    expect(pipe.transform(face({ expression_score: 4 }), thresholds)).toBe(false);
  });

  it('returns false when expression_score is absent', () => {
    expect(pipe.transform(face(), thresholds)).toBe(false);
  });

  it('returns false when thresholds have not loaded yet', () => {
    expect(pipe.transform(face({ expression_score: 2 }), null)).toBe(false);
  });
});

describe('FaceRingClassPipe', () => {
  const pipe = new FaceRingClassPipe();

  it('returns red when eyes_open_score is at or below eyes_closed_max', () => {
    expect(pipe.transform(face({ eyes_open_score: 4, smile_score: 8 }), thresholds)).toBe('ring-red-500');
  });

  it('returns orange when eyes are fine but smile_score is below poor_expression_min', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 2 }), thresholds)).toBe('ring-orange-500');
  });

  it('prioritizes red (eyes closed) over orange (poor smile)', () => {
    expect(pipe.transform(face({ eyes_open_score: 1, smile_score: 1 }), thresholds)).toBe('ring-red-500');
  });

  it('returns green when both signals are above their cutoffs', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 7 }), thresholds)).toBe('ring-green-500');
  });

  it('returns green when only one signal is present and fine', () => {
    expect(pipe.transform(face({ eyes_open_score: 8 }), thresholds)).toBe('ring-green-500');
  });

  it('returns neutral when both signals are missing (turned head)', () => {
    expect(pipe.transform(face(), thresholds)).toBe('ring-white/20');
  });

  it('returns neutral when thresholds have not loaded yet', () => {
    expect(pipe.transform(face({ eyes_open_score: 1 }), null)).toBe('ring-white/20');
  });
});

describe('FaceDimmedPipe', () => {
  const pipe = new FaceDimmedPipe();

  it('never dims when both sliders are at 0 (filter off)', () => {
    expect(pipe.transform(face({ eyes_open_score: 1, smile_score: 1 }), 0, 0)).toBe(false);
  });

  it('keeps faces below the eyes slider bright and dims the rest', () => {
    expect(pipe.transform(face({ eyes_open_score: 3 }), 5, 0)).toBe(false);
    expect(pipe.transform(face({ eyes_open_score: 8 }), 5, 0)).toBe(true);
  });

  it('keeps faces below the smile slider bright and dims the rest', () => {
    expect(pipe.transform(face({ smile_score: 2 }), 0, 5)).toBe(false);
    expect(pipe.transform(face({ smile_score: 8 }), 0, 5)).toBe(true);
  });

  it('stays bright when below either of two active sliders', () => {
    expect(pipe.transform(face({ eyes_open_score: 8, smile_score: 2 }), 5, 5)).toBe(false);
  });

  it('dims faces with no signals while a slider is active', () => {
    expect(pipe.transform(face(), 5, 0)).toBe(true);
  });
});

describe('SortIconPipe', () => {
  const pipe = new SortIconPipe();

  it('maps each known sort mode to its icon', () => {
    expect(pipe.transform('easiest')).toBe('bolt');
    expect(pipe.transform('redundant')).toBe('content_copy');
    expect(pipe.transform('best')).toBe('star');
    expect(pipe.transform('recent')).toBe('schedule');
    expect(pipe.transform('needs_comparisons')).toBe('compare_arrows');
  });

  it('falls back to the generic sort icon for an unknown mode', () => {
    expect(pipe.transform('whatever')).toBe('sort');
  });
});

describe('CullProfileIconPipe', () => {
  const pipe = new CullProfileIconPipe();

  it('maps each shipped profile to its icon', () => {
    expect(pipe.transform('balanced')).toBe('balance');
    expect(pipe.transform('wedding')).toBe('favorite');
    expect(pipe.transform('sports')).toBe('directions_run');
    expect(pipe.transform('concert')).toBe('music_note');
    expect(pipe.transform('wildlife')).toBe('pets');
  });

  it('falls back to the theatre mask for unknown / empty profiles', () => {
    expect(pipe.transform('custom_preset')).toBe('theaters');
    expect(pipe.transform('')).toBe('theaters');
    expect(pipe.transform(null)).toBe('theaters');
    expect(pipe.transform(undefined)).toBe('theaters');
  });
});

describe('CategoryIconPipe', () => {
  const pipe = new CategoryIconPipe();
  const ICONS = (CategoryIconPipe as unknown as { ICONS: Record<string, string> }).ICONS;

  it('maps known categories to sensible distinct icons', () => {
    expect(pipe.transform('portrait')).toBe('person');
    expect(pipe.transform('landscape')).toBe('landscape');
    expect(pipe.transform('sports')).toBe('sports_soccer');
    expect(pipe.transform('golden_hour')).toBe('wb_twilight');
    expect(pipe.transform('urban')).toBe('location_city');
    expect(pipe.transform('human_others')).toBe('people');
  });

  it('falls back to the generic category icon for unknown / empty values', () => {
    expect(pipe.transform('user_defined_genre')).toBe('category');
    expect(pipe.transform('')).toBe('category');
    expect(pipe.transform(null)).toBe('category');
    expect(pipe.transform(undefined)).toBe('category');
  });

  it('assigns a pairwise-distinct icon to every mapped category', () => {
    const icons = Object.values(ICONS);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it('never reuses the generic fallback icon for a mapped category', () => {
    expect(Object.values(ICONS)).not.toContain('category');
  });
});

describe('CullPreviewUrlPipe', () => {
  const pipe = new CullPreviewUrlPipe();

  it('builds the cull_preview endpoint URL with encoded path and style', () => {
    expect(pipe.transform('/a/b c.jpg', 'Velvia look'))
      .toBe('/api/photo/cull_preview?path=%2Fa%2Fb+c.jpg&style=Velvia+look');
  });
});
