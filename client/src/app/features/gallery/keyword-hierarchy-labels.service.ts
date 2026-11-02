import { Injectable, Pipe, PipeTransform, inject, signal } from '@angular/core';
import { AuthService, type AuthStatus } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';

/** Display names only; no persisted history or mutation authority. */
@Injectable({ providedIn: 'root' })
export class KeywordHierarchyLabels {
  private readonly auth = inject(AuthService);
  private readonly snapshot = signal<{ owner: string; status: AuthStatus | null; token: string | null; names: Record<string, string> } | null>(null);
  // token is a live storage getter, not a signal: never memoize this check.
  names(): Record<string, string> {
    const value = this.snapshot();
    return value && value.owner === this.auth.identity() && value.status === this.auth.status() && value.token === this.auth.token
      ? value.names : {};
  }
  remember(nodes: { id: string; segments: string[] }[]): void {
    this.snapshot.set({ owner: this.auth.identity(), status: this.auth.status(), token: this.auth.token,
      names: Object.fromEntries(nodes.map(node => [node.id, node.segments.join(' › ')])) });
  }
}

/** Resolve at rendering, outside the memoized criteria array. */
@Pipe({ name: 'keywordBranchLabel', standalone: true, pure: false })
export class KeywordBranchLabelPipe implements PipeTransform {
  private readonly labels = inject(KeywordHierarchyLabels);
  private readonly i18n = inject(I18nService);
  transform(id: string | undefined): string {
    return (id ? this.labels.names()[id] : undefined) ?? this.i18n.t(I18N.keyword_hierarchy.unavailable);
  }
}
