import { parseScorePresence, serializeScorePresence } from './score-presence.util';
import { DEFAULT_FILTERS, applyQueryParams, buildApiParams, buildSyncParams, applySavedAlbumFilters, smartAlbumFilterJson } from './gallery-filters.util';

describe('measurement policy codec', () => {
  it.each(['null', '[]', '{"min_star_rating":"missing_only"}', '{"min_sharpness":true}', '{"min_sharpness":"missing_only","min_sharpness":"include_missing"}', '{"min_sharpness":"missing_only","min_sharpne\\u0073s":"include_missing"}'])('refuses malformed policies %s', raw => {
    expect(parseScorePresence(raw)).toBeNull();
  });
  it('round trips per-metric rules and explicit cleared saved-album overrides', () => {
    const raw = serializeScorePresence({ min_sharpness: 'include_missing', min_face_quality: 'missing_only' });
    const f = { ...DEFAULT_FILTERS, score_presence: raw, min_sharpness: '2', album_id: '42' };
    expect(buildApiParams(f, false, undefined)['score_presence']).toBe(raw);
    expect(applyQueryParams(DEFAULT_FILTERS, buildSyncParams(f, undefined))).toMatchObject({ score_presence: raw, min_sharpness: '2' });
    const saved = applySavedAlbumFilters(DEFAULT_FILTERS, smartAlbumFilterJson(f), '42');
    expect(saved.score_presence).toBe(raw);
    const cleared = buildSyncParams({ ...saved, score_presence: '' }, undefined);
    expect(cleared['score_presence']).toBe('');
    expect(applyQueryParams(saved, cleared).score_presence).toBe('');
    expect(() => applySavedAlbumFilters(DEFAULT_FILTERS, '{"score_presence":false}', '42')).toThrow();
  });
});
