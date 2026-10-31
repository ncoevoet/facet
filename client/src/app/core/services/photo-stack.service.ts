import { Injectable, inject, signal } from '@angular/core';
import { tap } from 'rxjs';
import { GuardsCheckEnd, NavigationStart, ResolveEnd, Router } from '@angular/router';
import { components } from '../api/schema';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { Photo } from '../../shared/models/photo.model';

export type PhotoStack = components['schemas']['PhotoStack'];
export type StackMutation = components['schemas']['StackMutation'];
export type StackRegroupPreview = components['schemas']['StackRegroupPreview'];
export type StackRegroupMutation = components['schemas']['StackRegroupMutation'];
export type StackRegroupMode = StackRegroupPreview['mode'];
export type StackSuggestionKind = components['schemas']['StackSuggestionDismissal']['kind'];

/** Manual stacks only organize references; individual photo actions keep their exact scope. */
@Injectable({ providedIn: 'root' })
export class PhotoStackService {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private navigation = 0;
  readonly revision = signal(0);
  private changed = () => this.revision.update(value => value + 1);

  constructor() {
    this.router.events.subscribe(event => { if (event instanceof NavigationStart) this.navigation++; });
  }

  /** Root-owned epoch survives dialog destruction and detects leaving and returning before Undo. */
  context(): () => boolean {
    const owner = this.auth.identity();
    const navigation = this.navigation;
    const url = this.router.url;
    return () => owner === this.auth.identity() && navigation === this.navigation && url === this.router.url;
  }

  /** A write's epoch and account are still the ones that started it, and the account may still edit. */
  isLive(session: () => boolean): boolean { return session() && this.auth.isEdition(); }

  /** Guard for deferred work (an Undo outlives the page and the account that made the change). */
  assertLive(session: () => boolean): void {
    if (!this.isLive(session)) throw new Error('Stack session expired');
  }

  /** Recheck a live exact-list boundary after asynchronous guards and resolvers too. */
  async navigateMember(path: string, photo: Photo, allowed: () => boolean, replaceUrl: boolean): Promise<boolean> {
    const owner = this.auth.identity();
    const valid = () => owner === this.auth.identity() && allowed();
    if (!valid()) return false;
    const source = this.router.url;
    let navigationId: number | null = null;
    let cancelling = false;
    const subscription = this.router.events.subscribe(event => {
      if (event instanceof NavigationStart && navigationId === null) {
        const target = new URL(event.url, 'http://facet.invalid');
        if (target.pathname === '/photo' && target.searchParams.get('path') === path) navigationId = event.id;
      }
      if ((event instanceof GuardsCheckEnd || event instanceof ResolveEnd) && event.id === navigationId && !valid() && !cancelling) {
        cancelling = true;
        // Supersede this navigation before activation consumes its cached photo.
        void this.router.navigateByUrl(source, { replaceUrl: true });
      }
    });
    try {
      return await this.router.navigate(['/photo'], { queryParams: { path }, state: { photo }, replaceUrl });
    } finally { subscription.unsubscribe(); }
  }

  previewRegroup(selectedPaths: string[], mode: StackRegroupMode) {
    return this.api.post<StackRegroupPreview>('/stacks/regroup/preview', { selected_paths: selectedPaths, mode });
  }
  regroup(preview: StackRegroupPreview, paths: string[], cover: string) {
    const body: components['schemas']['StackRegroupApply'] = {
      selected_paths: preview.selected_paths, mode: preview.mode, expected_state: preview.expected_state,
      paths, cover_path: cover,
    };
    const session = this.context();
    return this.api.post<StackRegroupMutation>('/stacks/regroup/apply', body).pipe(tap(result => {
      if (result.changed && this.isLive(session)) this.changed();
    }));
  }

  get(id: string) { return this.api.get<PhotoStack | null>(`/stacks/${encodeURIComponent(id)}`); }
  byPhoto(path: string) { return this.api.get<PhotoStack | null>('/stacks/by-photo', { path }); }
  create(paths: string[], cover: string) {
    return this.api.post<StackMutation>('/stacks', { paths, cover_path: cover }).pipe(tap(this.changed));
  }
  update(stack: PhotoStack, paths: string[], cover: string | null) {
    return this.api.put<StackMutation>(`/stacks/${encodeURIComponent(stack.id)}`,
      { paths, cover_path: cover, expected_revision: stack.revision }).pipe(tap(this.changed));
  }
  unstack(stack: PhotoStack) {
    return this.api.delete<StackMutation>(`/stacks/${encodeURIComponent(stack.id)}?expected_revision=${stack.revision}`).pipe(tap(this.changed));
  }
  dismissSuggestion(kind: StackSuggestionKind, paths: string[]) {
    return this.api.post<void>('/stacks/suggestions/dismissals', { kind, paths });
  }
  restoreSuggestion(key: string) { return this.api.delete<void>(`/stacks/suggestions/dismissals/${key}`); }
  revert(entryId: number) { return this.api.post(`/organization_history/${entryId}/revert`, {}).pipe(tap(this.changed)); }
}
