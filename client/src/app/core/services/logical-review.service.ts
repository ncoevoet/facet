import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import type { components } from '../api/schema';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';

export type LogicalReviewState = components['schemas']['LogicalReviewState'];
export type LogicalReviewAction = { rating: number } | 'favorite' | 'reject' | 'kept' | 'undecided';

export class LogicalReviewWriteError extends Error {
  constructor(readonly recovered: LogicalReviewState | null) { super('Logical review was not confirmed'); }
}

@Injectable({ providedIn: 'root' })
export class LogicalReviewService {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly pending = new Set<string>();

  /** Explicit snapshot write, never a retry or a physical-file fallback. */
  async save(state: LogicalReviewState, action: LogicalReviewAction, valid: () => boolean): Promise<LogicalReviewState | null> {
    const owner = this.auth.identity();
    const token = this.auth.token;
    const key = JSON.stringify([owner, token, state.asset_id]);
    const current = () => this.auth.identity() === owner && this.auth.token === token && valid();
    if (!current() || this.pending.has(key)) return null;
    this.pending.add(key);
    const values = state.values;
    const patch: Record<string, number> = {};
    if (typeof action === 'object') patch['star_rating'] = action.rating;
    else if (action === 'favorite') {
      patch['is_favorite'] = values['is_favorite'] ? 0 : 1;
      if (patch['is_favorite']) {
        patch['is_kept'] = values['is_kept'] ? 1 : 0;
        patch['is_rejected'] = 0;
      }
    } else if (action === 'reject') {
      patch['is_rejected'] = values['is_rejected'] ? 0 : 1;
      patch['is_kept'] = 0;
      if (patch['is_rejected']) {
        patch['star_rating'] = 0;
        patch['is_favorite'] = 0;
      }
    } else {
      patch['is_kept'] = action === 'kept' ? 1 : 0;
      patch['is_rejected'] = 0;
    }
    try {
      const result = await firstValueFrom(this.api.post<LogicalReviewState>('/logical_assets/review', {
        asset_id: state.asset_id, group_revision: state.group_revision,
        revision: state.revision, input_token: state.input_token, patch,
      }));
      return current() ? result : null;
    } catch {
      if (!current()) return null;
      let recovered: LogicalReviewState | null = null;
      try {
        recovered = await firstValueFrom(this.api.get<LogicalReviewState>('/logical_assets/review', { asset_id: state.asset_id }));
      } catch { /* A failed repair leaves the displayed snapshot unchanged. */ }
      if (!current()) return null;
      throw new LogicalReviewWriteError(recovered);
    } finally { this.pending.delete(key); }
  }
}
