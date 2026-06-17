import {
  IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe,
  CullingGroup,
} from './burst-culling.pipes';

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
