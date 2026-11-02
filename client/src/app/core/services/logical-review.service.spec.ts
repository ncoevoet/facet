import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { LogicalReviewService, LogicalReviewState } from './logical-review.service';

const state: LogicalReviewState = {
  asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'snapshot', source_path: '/a.jpg',
  values: { star_rating: 4, is_favorite: 0, is_kept: 1, is_rejected: 0 },
  origins: { star_rating: 'file', is_favorite: 'file', is_kept: 'file', is_rejected: 'file' },
};

describe('LogicalReviewService', () => {
  let owner: string;
  let token: string;
  const post = vi.fn();
  const get = vi.fn();
  let service: LogicalReviewService;
  beforeEach(() => {
    owner = 'one'; token = 'token'; post.mockReset(); get.mockReset(); get.mockReturnValue(of(state));
    TestBed.configureTestingModule({ providers: [
      { provide: ApiService, useValue: { post, get } },
      { provide: AuthService, useValue: { identity: () => owner, get token() { return token; } } },
    ] });
    service = TestBed.inject(LogicalReviewService);
  });

  it('sends the snapshot and one atomic reject decision without physical writes', async () => {
    post.mockReturnValue(of(state));
    expect(await service.save(state, 'reject', () => true)).toEqual(state);
    expect(post).toHaveBeenCalledExactlyOnceWith('/logical_assets/review', {
      asset_id: 'asset', group_revision: 1, revision: 0, input_token: 'snapshot',
      patch: { is_rejected: 1, is_kept: 0, star_rating: 0, is_favorite: 0 },
    });
  });

  it('shares an in-flight lock across actions and representations', async () => {
    const pending = new Subject<LogicalReviewState>(); post.mockReturnValue(pending);
    const first = service.save(state, { rating: 2 }, () => true);
    expect(await service.save({ ...state }, 'favorite', () => true)).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
    pending.next({ ...state, revision: 1 }); pending.complete();
    expect((await first)?.revision).toBe(1);
    post.mockReturnValue(of(state));
    expect(await service.save(state, 'favorite', () => true)).toEqual(state);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it.each(['owner', 'token', 'navigation'])('suppresses a completion after %s changes', async change => {
    let current = true;
    const pending = new Subject<LogicalReviewState>(); post.mockReturnValue(pending);
    const result = service.save(state, 'kept', () => current);
    if (change === 'owner') owner = 'two';
    else if (change === 'token') token = 'new';
    else current = false;
    pending.next(state); pending.complete();
    expect(await result).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('refuses an obsolete action before writing and never retries a failed write', async () => {
    expect(await service.save(state, 'undecided', () => false)).toBeNull();
    expect(post).not.toHaveBeenCalled();
    post.mockReturnValue(throwError(() => new Error('uncertain completion')));
    await expect(service.save(state, { rating: 3 }, () => true)).rejects.toThrow();
    expect(post).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledExactlyOnceWith('/logical_assets/review', { asset_id: 'asset' });
  });
});
