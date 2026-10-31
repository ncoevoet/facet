import { StackRegroupPreview } from '../../core/services/photo-stack.service';
import { reconcileRegroupDraft, regroupSourceEffects } from './stack-regroup-state';

const preview: StackRegroupPreview = {
  selected_paths: ['/a', '/d'], mode: 'combine', paths: ['/a', '/b', '/c', '/d'], cover_path: '/a',
  source_stacks: [{ id: 's', revision: 1, editable: true, cover_path: '/a',
    members: ['/a', '/b', '/c'].map((path, position) => ({ path, position })) }],
  unstacked_paths: ['/d'], affected_paths: ['/a', '/b', '/c', '/d'], expected_state: 'a'.repeat(64),
};

describe('regroup draft reconciliation', () => {
  it('uses the authoritative candidate order and cover for a fresh draft', () => {
    expect(reconcileRegroupDraft(preview, null, new Set())).toEqual({ paths: ['/a', '/b', '/c', '/d'], cover: '/a' });
  });
  it('preserves surviving manual order and exclusions, replacing an invalid cover and appending new members', () => {
    expect(reconcileRegroupDraft({ ...preview, paths: ['/a', '/b', '/d', '/e'] },
      { paths: ['/d', '/c', '/a'], cover: '/c' }, new Set(['/b'])))
      .toEqual({ paths: ['/d', '/a', '/e'], cover: '/a' });
  });
  it('preserves the chosen cover and relative order when changing to selected only', () => {
    expect(reconcileRegroupDraft({ ...preview, mode: 'selected', paths: ['/a', '/d'] },
      { paths: ['/d', '/c', '/a'], cover: '/d' }, new Set(['/b'])))
      .toEqual({ paths: ['/d', '/a'], cover: '/d' });
  });
  it('never restores explicitly excluded photos, even when every candidate was removed', () => {
    expect(reconcileRegroupDraft(preview, { paths: [], cover: '' }, new Set(preview.paths)))
      .toEqual({ paths: [], cover: '' });
  });
  it.each([
    [['/a', '/d'], 1, 2, 'regroup_retained'],
    [['/a', '/b', '/d'], 2, 1, 'regroup_singleton'],
    [['/a', '/b', '/c', '/d'], 3, 0, 'regroup_absorbed'],
  ] as const)('describes the actual residual source for %j', (paths, moved, remaining, outcome) => {
    expect(regroupSourceEffects(preview, paths)).toEqual([{ id: 's', cover: '/a', total: 3, moved, remaining, outcome }]);
  });
});
