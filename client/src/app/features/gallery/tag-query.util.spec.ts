import { hasTagQuery, parseTagQuery, serializeTagQuery, refineTagQuery } from './tag-query.util';
import { applyQueryParams, applySavedAlbumFilters, buildSyncParams, DEFAULT_FILTERS } from './gallery-filters.util';

describe('literal tag groups', () => {
  it('refines with a literal AND while retaining existing alternatives and exclusions', () => {
    const raw = serializeTagQuery({ any: ['a', 'b'], all: [], none: ['c'] });
    const refined = refineTagQuery(raw, 'coast,ridge OR 夜景');
    expect(parseTagQuery(refined!)).toEqual({ any: ['a', 'b'], all: ['coast,ridge OR 夜景'], none: ['c'] });
    expect(refineTagQuery(refined!, 'coast,ridge OR 夜景')).toBe(refined);
    expect(refineTagQuery('{invalid', 'a')).toBeNull();
    expect(refineTagQuery(serializeTagQuery({ any: Array.from({ length: 50 }, (_, i) => String(i)), all: [], none: [] }), 'extra')).toBeNull();
  });
  it('round trips comma, operator-like, quoted and Unicode names as single entities', () => {
    const groups = { any: ['coast,ridge', 'a OR b', '"quote"', '夜景', '📷'.repeat(200)], all: ['a'], none: ['%_'] };
    const raw = serializeTagQuery(groups);
    expect(parseTagQuery(raw)).toEqual(groups);
    expect(hasTagQuery(raw)).toBe(true);
    const params = buildSyncParams({ ...DEFAULT_FILTERS, tag_groups: raw }, undefined);
    expect(applyQueryParams(DEFAULT_FILTERS, params).tag_groups).toBe(raw);
  });

  it.each([
    '{"any":["a"],"any":["b"]}',
    '{"any":["a"],"\\u0061ny":["b"]}',
    '{"any":["\\ud800"]}', '{"any":["\\n"]}',
    '{"any":"a"}', '{"unknown":[]}', JSON.stringify({ all: ['📷'.repeat(201)] }),
    JSON.stringify({ any: Array.from({ length: 51 }, (_, i) => String(i)) }),
  ])('refuses malformed or ambiguous groups rather than dropping constraints: %s', raw => {
    expect(parseTagQuery(raw)).toBeNull();
    expect(hasTagQuery(raw)).toBe(true);
  });

  it('serializes an explicit empty override over saved-album groups', () => {
    const saved = applySavedAlbumFilters(DEFAULT_FILTERS, JSON.stringify({ tag_groups: '{"all":["saved"]}' }), '3');
    const cleared = applyQueryParams(saved, { tag_groups: '' });
    expect(cleared.tag_groups).toBe('');
    expect(buildSyncParams({ ...cleared, album_id: '3' }, undefined)['tag_groups']).toBe('');
    expect(parseTagQuery('{"any":[],"none":[]}')).toEqual({ any: [], all: [], none: [] });
    expect(hasTagQuery('{}')).toBe(false);
  });
});
