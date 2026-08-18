import { Photo, normalisePhotoFlags, normalisePhotoFlagsAll } from './photo.model';

function wire(overrides: Record<string, unknown> = {}): Photo {
  return {
    path: '/a.jpg',
    filename: 'a.jpg',
    aggregate: 7,
    ...overrides,
  } as unknown as Photo;
}

describe('normalisePhotoFlags', () => {
  it('turns the 0/1 flag columns the API sends into real booleans', () => {
    const p = normalisePhotoFlags(wire({
      is_blink: 1,
      is_monochrome: 0,
      is_silhouette: 1,
      is_burst_lead: 1,
      is_duplicate_lead: 0,
      is_favorite: 1,
      is_rejected: 0,
    }));
    expect(p.is_blink).toBe(true);
    expect(p.is_monochrome).toBe(false);
    expect(p.is_silhouette).toBe(true);
    expect(p.is_burst_lead).toBe(true);
    expect(p.is_duplicate_lead).toBe(false);
    expect(p.is_favorite).toBe(true);
    expect(p.is_rejected).toBe(false);
  });

  it('preserves null rather than folding it to false', () => {
    // is_favorite/is_rejected are NULL on almost every row of a real library —
    // the per-user values live in user_preferences — and photo-detail treats
    // null as "the server has no opinion, keep what we have".
    const p = normalisePhotoFlags(wire({ is_favorite: null, is_rejected: null, is_blink: null }));
    expect(p.is_favorite).toBeNull();
    expect(p.is_rejected).toBeNull();
    expect(p.is_blink).toBeNull();
  });

  it('leaves an absent flag absent', () => {
    const p = normalisePhotoFlags(wire());
    expect('is_favorite' in p).toBe(false);
    expect(p.is_favorite).toBeUndefined();
  });

  it('does not touch non-flag fields', () => {
    const p = normalisePhotoFlags(wire({ aggregate: 0, star_rating: 0, face_count: 1 }));
    expect(p.aggregate).toBe(0);
    expect(p.star_rating).toBe(0);
    expect(p.face_count).toBe(1);
  });

  it('does not mutate the object it was given', () => {
    const source = wire({ is_favorite: 1 });
    const out = normalisePhotoFlags(source);
    expect((source as unknown as Record<string, unknown>)['is_favorite']).toBe(1);
    expect(out.is_favorite).toBe(true);
    expect(out).not.toBe(source);
  });

  it('normalises every photo in a payload', () => {
    const out = normalisePhotoFlagsAll([
      wire({ path: '/a.jpg', is_favorite: 1 }),
      wire({ path: '/b.jpg', is_favorite: 0 }),
      wire({ path: '/c.jpg', is_favorite: null }),
    ]);
    expect(out.map(p => p.is_favorite)).toEqual([true, false, null]);
    expect(out.map(p => p.path)).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
  });
});
