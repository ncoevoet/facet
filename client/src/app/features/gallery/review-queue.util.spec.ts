import { DEFAULT_FILTERS } from './gallery-filters.util';
import { readReviewQueue, saveReviewQueue } from './review-queue.util';

describe('browser review queue', () => {
  beforeEach(() => localStorage.removeItem('facet_review_queues_v1'));
  const filters = { ...DEFAULT_FILTERS, review_status: 'undecided' as const, path_prefix: '/trip/', camera: 'TripCam' };

  it('round-trips known scope filters after reload without a photo cursor or transient group ids', () => {
    saveReviewQueue('1|alice', { ...filters, page: 22 });
    expect(readReviewQueue('1|alice')?.filters).toMatchObject({ camera: 'TripCam', path_prefix: '/trip/', page: 1, burst_group_id: '' });
    expect(readReviewQueue('1|bob')).toBeNull();
    expect(readReviewQueue('0|')).toBeNull();
  });

  it('keeps the stable queue instead of persisting rescan-assigned group ids', () => {
    saveReviewQueue('1|alice', filters);
    saveReviewQueue('1|alice', { ...filters, path_prefix: '/temporary/', burst_group_id: '99' });
    expect(readReviewQueue('1|alice')?.filters.path_prefix).toBe('/trip/');
  });

  it('retains at most 20 users and replaces only the current user bookmark', () => {
    for (let i = 0; i < 25; i++) saveReviewQueue(`1|${i}`, filters);
    expect(readReviewQueue('1|0')).toBeNull();
    expect(readReviewQueue('1|24')).not.toBeNull();
    saveReviewQueue('1|24', { ...filters, camera: 'Updated' });
    expect(readReviewQueue('1|24')?.filters.camera).toBe('Updated');
    expect(JSON.parse(localStorage.getItem('facet_review_queues_v1')!)).toHaveLength(20);
  });

  it('rejects malformed, wrong-typed and oversized persisted queues', () => {
    for (const raw of ['{broken', '{}', JSON.stringify([['1|alice', { filters: { ...filters, camera: 5 } }]]),
      JSON.stringify([['1|alice', { filters: { ...filters, camera: 'a'.repeat(2049) } }]])]) {
      localStorage.setItem('facet_review_queues_v1', raw);
      expect(readReviewQueue('1|alice')).toBeNull();
    }
  });

  it('does not interrupt reviewing when browser storage is denied or full', () => {
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceededError'); });
    expect(() => saveReviewQueue('1|alice', filters)).not.toThrow();
    set.mockRestore();
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('SecurityError'); });
    expect(readReviewQueue('1|alice')).toBeNull();
    get.mockRestore();
  });
});
