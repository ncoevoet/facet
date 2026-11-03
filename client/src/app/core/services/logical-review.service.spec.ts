import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { LogicalReviewService, LogicalReviewState, LogicalReviewWriteError } from './logical-review.service';

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

  it.each([
    [{ rating: 3 }, state, { star_rating: 3 }],
    ['favorite', state, { is_favorite: 1, is_kept: 1, is_rejected: 0 }],
    ['favorite', { ...state, values: { ...state.values, is_favorite: 1 } }, { is_favorite: 0 }],
    ['reject', { ...state, values: { ...state.values, is_rejected: 1 } }, { is_rejected: 0, is_kept: 0 }],
    ['kept', state, { is_kept: 1, is_rejected: 0 }],
    ['undecided', state, { is_kept: 0, is_rejected: 0 }],
  ] as const)('writes the intended patch for %s', async (action, snapshot, patch) => {
    post.mockReturnValue(of(state));
    await service.save(snapshot, action, () => true);
    expect(post).toHaveBeenCalledWith('/logical_assets/review', expect.objectContaining({ patch }));
  });

  it('exposes a recovered snapshot or a failed repair without retrying the write', async () => {
    const recovered = { ...state, revision: 2 };
    post.mockReturnValue(throwError(() => new Error('lost response')));
    get.mockReturnValueOnce(of(recovered)).mockReturnValueOnce(throwError(() => new Error('offline')));
    await expect(service.save(state, 'kept', () => true)).rejects.toMatchObject({ recovered });
    await expect(service.save(state, 'kept', () => true)).rejects.toEqual(new LogicalReviewWriteError(null));
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('suppresses a recovered snapshot when the account changes during repair', async () => {
    const pending = new Subject<LogicalReviewState>();
    post.mockReturnValue(throwError(() => new Error('lost response'))); get.mockReturnValue(pending);
    const result = service.save(state, 'kept', () => true);
    owner = 'two'; pending.next(state); pending.complete();
    expect(await result).toBeNull();
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
