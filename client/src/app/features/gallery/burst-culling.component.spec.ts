import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { BurstCullingComponent, IsKeptPipe, IsDecidedPipe, IsConfirmedPipe, IsPassingPipe, PassCountdownPipe } from './burst-culling.component';

describe('BurstCullingComponent', () => {
  let component: BurstCullingComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };

  const mockCullingGroupsResponse = {
    groups: [
      {
        group_id: 1,
        type: 'burst',
        reason: '0.8s apart',
        photos: [
          { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8.5, aesthetic: 7.0, tech_sharpness: 6.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 9.0 },
          { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7.0, aesthetic: 6.5, tech_sharpness: 5.5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7.0 },
          { path: '/photo3.jpg', filename: 'photo3.jpg', aggregate: 5.0, aesthetic: 5.0, tech_sharpness: 4.0, is_blink: 1, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 4.0 },
        ],
        best_path: '/photo1.jpg',
        count: 3,
      },
      {
        group_id: 2,
        type: 'similar',
        reason: '85% similar',
        photos: [
          { path: '/photo4.jpg', filename: 'photo4.jpg', aggregate: 9.0, aesthetic: 8.5, tech_sharpness: 7.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-02', burst_score: 9.5 },
          { path: '/photo5.jpg', filename: 'photo5.jpg', aggregate: 6.0, aesthetic: 5.0, tech_sharpness: 5.0, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-02', burst_score: 5.5 },
        ],
        best_path: '/photo4.jpg',
        count: 2,
      },
    ],
    total_groups: 2,
    page: 1,
    per_page: 20,
    total_pages: 1,
  };

  beforeEach(() => {
    mockApi = {
      get: jest.fn(() => of(mockCullingGroupsResponse)),
      post: jest.fn(() => of({})),
    };
    mockSnackBar = { open: jest.fn() };
    mockI18n = { t: jest.fn((key: string) => key) };

    TestBed.configureTestingModule({
      providers: [
        BurstCullingComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    component = TestBed.inject(BurstCullingComponent);
  });

  afterEach(() => {
    component.ngOnDestroy();
  });

  describe('initial state', () => {
    it('should have loading as a signal function', () => {
      expect(typeof component['loading']).toBe('function');
    });

    it('should start with confirming false', () => {
      expect(component['confirming']()).toBe(false);
    });
  });

  describe('loadGroups', () => {
    it('should load culling groups from API', async () => {
      await (component as any).loadGroups();

      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: true }));
      expect(component['groups']()).toHaveLength(2);
      expect(component['totalGroups']()).toBe(2);
      expect(component['loading']()).toBe(false);
    });

    it('should update exclude_rejected value and reload on change', async () => {
      mockApi.get.mockClear();
      (component as any).onExcludeRejectedChange(false);

      expect(component['excludeRejected']()).toBe(false);
      expect(mockApi.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({ page: 1, per_page: 20, exclude_rejected: false }));
    });

    it('should auto-select best photo in each group', async () => {
      await (component as any).loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.get(1)?.has('/photo1.jpg')).toBe(true);
      expect(selections.get(2)?.has('/photo4.jpg')).toBe(true);
    });

    it('should not create selection entry for groups without best_path', async () => {
      mockApi.get.mockReturnValue(of({
        groups: [{ group_id: 10, type: 'burst', reason: '', photos: [], best_path: '', count: 0 }],
        total_groups: 1, page: 1, per_page: 20, total_pages: 1,
      }));

      await (component as any).loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.has(10)).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await (component as any).loadGroups();

      expect(component['loading']()).toBe(false);
    });

    it('should retain existing groups on error (no reset)', async () => {
      // First load succeeds
      await (component as any).loadGroups();
      expect(component['groups']()).toHaveLength(2);

      // Second load fails — groups remain from the first load
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      await (component as any).loadGroups();

      expect(component['groups']()).toHaveLength(2);
    });
  });

  describe('loadMore', () => {
    it('should append groups from the next page', async () => {
      await (component as any).loadGroups();
      component['totalPages'].set(2);

      const page2Response = {
        groups: [{ group_id: 3, type: 'burst', reason: '1s apart', photos: [], best_path: '', count: 0 }],
        total_groups: 3, page: 2, per_page: 20, total_pages: 2,
      };
      mockApi.get.mockReturnValue(of(page2Response));

      await (component as any).loadMore();

      expect(component['groups']()).toHaveLength(3);
      expect(component['currentPage']()).toBe(2);
    });

    it('should not load if no more pages', async () => {
      await (component as any).loadGroups();
      mockApi.get.mockClear();

      await (component as any).loadMore();

      expect(mockApi.get).not.toHaveBeenCalled();
    });
  });

  describe('toggleSelection', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    it('should add a photo to the selection when not already selected', () => {
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo2.jpg')).toBe(true);
    });

    it('should remove a photo from the selection when already selected', () => {
      const group = component['groups']()[0];
      // photo1.jpg is auto-selected as best_path
      component['toggleSelection']('/photo1.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(false);
    });

    it('should allow multiple photos to be selected', () => {
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);
      component['toggleSelection']('/photo3.jpg', group);

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(true); // auto-selected
      expect(kept?.has('/photo2.jpg')).toBe(true);
      expect(kept?.has('/photo3.jpg')).toBe(true);
    });

    it('should not mutate original map', () => {
      const originalMap = component['selectionsMap']();
      const group = component['groups']()[0];
      component['toggleSelection']('/photo2.jpg', group);
      const newMap = component['selectionsMap']();

      expect(newMap).not.toBe(originalMap);
    });
  });

  describe('confirmGroup', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('should post selected paths to API', async () => {
      const group = component['groups']()[0];
      await component['confirmGroup'](group);

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', {
        group_id: 1,
        type: 'burst',
        paths: ['/photo1.jpg', '/photo2.jpg', '/photo3.jpg'],
        keep_paths: ['/photo1.jpg'],
      });
    });

    it('should show snackbar on success', async () => {
      const group = component['groups']()[0];
      await component['confirmGroup'](group);

      expect(mockSnackBar.open).toHaveBeenCalledWith('culling.confirmed', '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    });

    it('should add group to confirmedGroups on success', async () => {
      const group = component['groups']()[0];
      await component['confirmGroup'](group);

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
    });

    it('should set confirming to true during request', async () => {
      let confirmingDuringRequest = false;
      mockApi.post.mockImplementation(() => {
        confirmingDuringRequest = component['confirming']();
        return of({});
      });

      const group = component['groups']()[0];
      await component['confirmGroup'](group);

      expect(confirmingDuringRequest).toBe(true);
    });

    it('should set confirming back to false after request', async () => {
      const group = component['groups']()[0];
      await component['confirmGroup'](group);

      expect(component['confirming']()).toBe(false);
    });

    it('should not post if no photos are selected', async () => {
      // Clear the auto-selection
      component['selectionsMap'].set(new Map());
      const group = component['groups']()[0];

      await component['confirmGroup'](group);

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should set confirming false on API error', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('Server error')));
      const group = component['groups']()[0];

      await component['confirmGroup'](group);

      expect(component['confirming']()).toBe(false);
    });
  });

  describe('skipGroup (pass with countdown)', () => {
    beforeEach(async () => {
      jest.useFakeTimers();
      await (component as any).loadGroups();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('should add group to passingGroups with countdown of 5', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      expect(component['passingGroups']().has('1_burst')).toBe(true);
      expect(component['passingGroups']().get('1_burst')).toBe(5);
      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should not add group to confirmedGroups immediately', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      expect(component['confirmedGroups']().has('1_burst')).toBe(false);
    });

    it('should decrement countdown every second', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      jest.advanceTimersByTime(1000);
      expect(component['passingGroups']().get('1_burst')).toBe(4);

      jest.advanceTimersByTime(1000);
      expect(component['passingGroups']().get('1_burst')).toBe(3);
    });

    it('should hide group after 5 seconds', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      jest.advanceTimersByTime(5000);

      // Group should be hidden (removed from visible groups)
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeUndefined();
      // But still in groups
      expect(component['groups']().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should remove group from passingGroups after timeout', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      jest.advanceTimersByTime(5000);

      expect(component['passingGroups']().has('1_burst')).toBe(false);
    });
  });

  describe('cancelPass', () => {
    beforeEach(async () => {
      jest.useFakeTimers();
      await (component as any).loadGroups();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('should remove group from passingGroups', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);
      expect(component['passingGroups']().has('1_burst')).toBe(true);

      component['cancelPass'](group);
      expect(component['passingGroups']().has('1_burst')).toBe(false);
    });

    it('should keep group visible after cancel', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      jest.advanceTimersByTime(2000);
      component['cancelPass'](group);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });

    it('should prevent auto-hide after cancel', () => {
      const group = component['groups']()[0];
      component['skipGroup'](group);

      jest.advanceTimersByTime(2000);
      component['cancelPass'](group);

      // Advance past original timeout
      jest.advanceTimersByTime(5000);

      // Group should still be visible
      expect(component['visibleGroups']().find(g => g.group_id === 1)).toBeDefined();
    });
  });

  describe('confirmAllRemaining', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('should post best_path for each remaining group', async () => {
      await component['confirmAllRemaining']();

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 1,
        type: 'burst',
        keep_paths: ['/photo1.jpg'],
      }));
      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 2,
        type: 'similar',
        keep_paths: ['/photo4.jpg'],
      }));
    });

    it('should mark all groups as confirmed', async () => {
      await component['confirmAllRemaining']();

      expect(component['confirmedGroups']().has('1_burst')).toBe(true);
      expect(component['confirmedGroups']().has('2_similar')).toBe(true);
    });

    it('should skip already confirmed groups', async () => {
      // Directly confirm group 1 (simulating a previously confirmed group)
      component['confirmedGroups'].update(s => {
        const next = new Set(s);
        next.add('1_burst');
        return next;
      });
      mockApi.post.mockClear();

      await component['confirmAllRemaining']();

      // Only group 2 should be posted (group 1 was already confirmed)
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({
        group_id: 2,
      }));
    });

    it('should set confirming false after completion', async () => {
      await component['confirmAllRemaining']();

      expect(component['confirming']()).toBe(false);
    });
  });

  describe('hasMore', () => {
    beforeEach(async () => {
      await (component as any).loadGroups();
    });

    it('should return false on single page', () => {
      expect(component['hasMore']()).toBe(false);
    });

    it('should return true when more pages exist', () => {
      component['totalPages'].set(2);
      expect(component['hasMore']()).toBe(true);
    });
  });
});

describe('IsKeptPipe', () => {
  const pipe = new IsKeptPipe();

  it('should return true when path is in the kept set for the burst', () => {
    const map = new Map<number, Set<string>>();
    map.set(1, new Set(['/photo1.jpg']));

    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(true);
  });

  it('should return false when path is not in the kept set', () => {
    const map = new Map<number, Set<string>>();
    map.set(1, new Set(['/photo1.jpg']));

    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(false);
  });

  it('should return false when burst_id has no entry', () => {
    const map = new Map<number, Set<string>>();

    expect(pipe.transform('/photo1.jpg', map, 99)).toBe(false);
  });
});

describe('IsDecidedPipe', () => {
  const pipe = new IsDecidedPipe();

  it('should return true when burst has selections and path is not kept', () => {
    const map = new Map<number, Set<string>>();
    map.set(1, new Set(['/photo1.jpg']));

    expect(pipe.transform('/photo2.jpg', map, 1)).toBe(true);
  });

  it('should return false when path is kept', () => {
    const map = new Map<number, Set<string>>();
    map.set(1, new Set(['/photo1.jpg']));

    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });

  it('should return false when burst has no entry', () => {
    const map = new Map<number, Set<string>>();

    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });

  it('should return false when kept set is empty', () => {
    const map = new Map<number, Set<string>>();
    map.set(1, new Set());

    expect(pipe.transform('/photo1.jpg', map, 1)).toBe(false);
  });
});

describe('IsConfirmedPipe', () => {
  const pipe = new IsConfirmedPipe();

  it('should return true when group is confirmed', () => {
    const group = { group_id: 1, type: 'burst' as const, reason: '', photos: [], best_path: '', count: 0 };
    const confirmed = new Set(['1_burst']);

    expect(pipe.transform(group as any, confirmed)).toBe(true);
  });

  it('should return false when group is not confirmed', () => {
    const group = { group_id: 2, type: 'similar' as const, reason: '', photos: [], best_path: '', count: 0 };
    const confirmed = new Set(['1_burst']);

    expect(pipe.transform(group as any, confirmed)).toBe(false);
  });

  it('should distinguish between burst and similar types', () => {
    const burstGroup = { group_id: 1, type: 'burst' as const, reason: '', photos: [], best_path: '', count: 0 };
    const similarGroup = { group_id: 1, type: 'similar' as const, reason: '', photos: [], best_path: '', count: 0 };
    const confirmed = new Set(['1_burst']);

    expect(pipe.transform(burstGroup as any, confirmed)).toBe(true);
    expect(pipe.transform(similarGroup as any, confirmed)).toBe(false);
  });
});

describe('IsPassingPipe', () => {
  const pipe = new IsPassingPipe();

  it('should return true when group is in passingGroups', () => {
    const group = { group_id: 1, type: 'burst' as const, reason: '', photos: [], best_path: '', count: 0 };
    const passing = new Map([['1_burst', 4]]);

    expect(pipe.transform(group as any, passing)).toBe(true);
  });

  it('should return false when group is not in passingGroups', () => {
    const group = { group_id: 2, type: 'similar' as const, reason: '', photos: [], best_path: '', count: 0 };
    const passing = new Map([['1_burst', 4]]);

    expect(pipe.transform(group as any, passing)).toBe(false);
  });
});

describe('PassCountdownPipe', () => {
  const pipe = new PassCountdownPipe();

  it('should return countdown value for group in passingGroups', () => {
    const group = { group_id: 1, type: 'burst' as const, reason: '', photos: [], best_path: '', count: 0 };
    const passing = new Map([['1_burst', 3]]);

    expect(pipe.transform(group as any, passing)).toBe(3);
  });

  it('should return 0 for group not in passingGroups', () => {
    const group = { group_id: 2, type: 'similar' as const, reason: '', photos: [], best_path: '', count: 0 };
    const passing = new Map([['1_burst', 3]]);

    expect(pipe.transform(group as any, passing)).toBe(0);
  });
});
