import { StackRegroupPreview } from '../../core/services/photo-stack.service';

export interface StackDraft { paths: string[]; cover: string }

/** Keep intentional exclusions and surviving order; append only newly available candidates. */
export function reconcileRegroupDraft(preview: StackRegroupPreview, previous: StackDraft | null,
  excluded: ReadonlySet<string>): StackDraft {
  const allowed = new Set(preview.paths.filter(path => !excluded.has(path)));
  const paths = previous?.paths.filter(path => allowed.has(path)) ?? [];
  const retained = new Set(paths);
  paths.push(...preview.paths.filter(path => allowed.has(path) && !retained.has(path)));
  const cover = previous && paths.includes(previous.cover) ? previous.cover
    : paths.includes(preview.cover_path) ? preview.cover_path : paths[0] ?? '';
  return { paths, cover };
}

/** Residual members stay in their source group, or become unstacked if only one remains. */
export function regroupSourceEffects(preview: StackRegroupPreview | null, paths: readonly string[]) {
  const destination = new Set(paths);
  return (preview?.source_stacks ?? []).map(source => {
    const remaining = source.members.filter(member => !destination.has(member.path));
    return { id: source.id, cover: source.cover_path, total: source.members.length,
      moved: source.members.length - remaining.length, remaining: remaining.length,
      outcome: remaining.length >= 2 ? 'regroup_retained' as const
        : remaining.length === 1 ? 'regroup_singleton' as const : 'regroup_absorbed' as const };
  });
}
