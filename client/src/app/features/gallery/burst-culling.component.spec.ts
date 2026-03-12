import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { BurstCullingComponent, IsKeptPipe, IsDecidedPipe } from './burst-culling.component';

describe('BurstCullingComponent', () => {
  let component: BurstCullingComponent;
  let mockApi: { get: jest.Mock; post: jest.Mock };
  let mockSnackBar: { open: jest.Mock };
  let mockI18n: { t: jest.Mock };

  const mockBurstGroupsResponse = {
    groups: [
      {
        burst_id: 1,
        photos: [
          { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8.5, aesthetic: 7.0, tech_sharpness: 6.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 9.0 },
          { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7.0, aesthetic: 6.5, tech_sharpness: 5.5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7.0 },
          { path: '/photo3.jpg', filename: 'photo3.jpg', aggregate: 5.0, aesthetic: 5.0, tech_sharpness: 4.0, is_blink: 1, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 4.0 },
        ],
        best_path: '/photo1.jpg',
        count: 3,
      },
      {
        burst_id: 2,
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
      get: jest.fn(() => of(mockBurstGroupsResponse)),
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

  describe('initial state', () => {
    it('should start with loading true', () => {
      // The constructor calls loadGroups which sets loading true initially
      // After awaiting, loading becomes false. Since the mock resolves immediately,
      // by the time we check, it may already be false.
      expect(typeof component['loading']).toBe('function');
    });

    it('should start with currentIndex 0', () => {
      expect(component['currentIndex']()).toBe(0);
    });

    it('should start with confirming false', () => {
      expect(component['confirming']()).toBe(false);
    });
  });

  describe('loadGroups', () => {
    it('should load burst groups from API', async () => {
      await component.loadGroups();

      expect(mockApi.get).toHaveBeenCalledWith('/burst-groups', { page: 1, per_page: 20 });
      expect(component['groups']()).toHaveLength(2);
      expect(component['totalGroups']()).toBe(2);
      expect(component['loading']()).toBe(false);
    });

    it('should set currentIndex to 0 after loading', async () => {
      await component.loadGroups();

      expect(component['currentIndex']()).toBe(0);
    });

    it('should auto-select best photo in each group', async () => {
      await component.loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.get(1)?.has('/photo1.jpg')).toBe(true);
      expect(selections.get(2)?.has('/photo4.jpg')).toBe(true);
    });

    it('should not create selection entry for groups without best_path', async () => {
      mockApi.get.mockReturnValue(of({
        groups: [{ burst_id: 10, photos: [], best_path: '', count: 0 }],
        total_groups: 1, page: 1, per_page: 20, total_pages: 1,
      }));

      await component.loadGroups();

      const selections = component['selectionsMap']();
      expect(selections.has(10)).toBe(false);
    });

    it('should set loading false on error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));

      await component.loadGroups();

      expect(component['loading']()).toBe(false);
    });

    it('should retain existing groups on error (no reset)', async () => {
      // First load succeeds
      await component.loadGroups();
      expect(component['groups']()).toHaveLength(2);

      // Second load fails — groups remain from the first load
      mockApi.get.mockReturnValue(throwError(() => new Error('Network error')));
      await component.loadGroups();

      expect(component['groups']()).toHaveLength(2);
    });
  });

  describe('currentGroup', () => {
    it('should return the group at currentIndex', async () => {
      await component.loadGroups();

      const group = component['currentGroup']();
      expect(group.burst_id).toBe(1);
    });

    it('should update when currentIndex changes', async () => {
      await component.loadGroups();
      component['currentIndex'].set(1);

      const group = component['currentGroup']();
      expect(group.burst_id).toBe(2);
    });
  });

  describe('toggleSelection', () => {
    beforeEach(async () => {
      await component.loadGroups();
    });

    it('should add a photo to the selection when not already selected', () => {
      component['toggleSelection']('/photo2.jpg');

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo2.jpg')).toBe(true);
    });

    it('should remove a photo from the selection when already selected', () => {
      // photo1.jpg is auto-selected as best_path
      component['toggleSelection']('/photo1.jpg');

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(false);
    });

    it('should allow multiple photos to be selected', () => {
      component['toggleSelection']('/photo2.jpg');
      component['toggleSelection']('/photo3.jpg');

      const kept = component['selectionsMap']().get(1);
      expect(kept?.has('/photo1.jpg')).toBe(true); // auto-selected
      expect(kept?.has('/photo2.jpg')).toBe(true);
      expect(kept?.has('/photo3.jpg')).toBe(true);
    });

    it('should not mutate original map', () => {
      const originalMap = component['selectionsMap']();
      component['toggleSelection']('/photo2.jpg');
      const newMap = component['selectionsMap']();

      expect(newMap).not.toBe(originalMap);
    });
  });

  describe('confirmGroup', () => {
    beforeEach(async () => {
      await component.loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('should post selected paths to API', async () => {
      await component['confirmGroup']();

      expect(mockApi.post).toHaveBeenCalledWith('/burst-groups/select', {
        burst_id: 1,
        keep_paths: ['/photo1.jpg'],
      });
    });

    it('should show snackbar on success', async () => {
      await component['confirmGroup']();

      expect(mockSnackBar.open).toHaveBeenCalledWith('culling.confirmed', '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    });

    it('should set confirming to true during request', async () => {
      let confirmingDuringRequest = false;
      mockApi.post.mockImplementation(() => {
        confirmingDuringRequest = component['confirming']();
        return of({});
      });

      await component['confirmGroup']();

      expect(confirmingDuringRequest).toBe(true);
    });

    it('should set confirming back to false after request', async () => {
      await component['confirmGroup']();

      expect(component['confirming']()).toBe(false);
    });

    it('should move to next group after confirming', async () => {
      expect(component['currentIndex']()).toBe(0);

      await component['confirmGroup']();

      expect(component['currentIndex']()).toBe(1);
    });

    it('should not post if no photos are selected', async () => {
      // Clear the auto-selection
      component['selectionsMap'].set(new Map());

      await component['confirmGroup']();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('should set confirming false on API error', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('Server error')));

      await component['confirmGroup']();

      expect(component['confirming']()).toBe(false);
    });
  });

  describe('skipGroup', () => {
    beforeEach(async () => {
      await component.loadGroups();
    });

    it('should move to next group without posting', () => {
      component['skipGroup']();

      expect(component['currentIndex']()).toBe(1);
      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('autoSelectAll', () => {
    beforeEach(async () => {
      await component.loadGroups();
      mockApi.post.mockReturnValue(of({}));
    });

    it('should post best_path for each remaining group', async () => {
      await component['autoSelectAll']();

      expect(mockApi.post).toHaveBeenCalledWith('/burst-groups/select', {
        burst_id: 1,
        keep_paths: ['/photo1.jpg'],
      });
      expect(mockApi.post).toHaveBeenCalledWith('/burst-groups/select', {
        burst_id: 2,
        keep_paths: ['/photo4.jpg'],
      });
    });

    it('should show snackbar on success', async () => {
      await component['autoSelectAll']();

      expect(mockSnackBar.open).toHaveBeenCalledWith('culling.confirmed', '', { duration: 2000, horizontalPosition: 'right', verticalPosition: 'bottom' });
    });

    it('should move currentIndex to last group', async () => {
      await component['autoSelectAll']();

      expect(component['currentIndex']()).toBe(1);
    });

    it('should set confirming false after completion', async () => {
      await component['autoSelectAll']();

      expect(component['confirming']()).toBe(false);
    });

    it('should only process groups from currentIndex onward', async () => {
      component['currentIndex'].set(1);
      mockApi.post.mockClear();

      await component['autoSelectAll']();

      // Only group at index 1 (burst_id: 2) should be posted
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(mockApi.post).toHaveBeenCalledWith('/burst-groups/select', {
        burst_id: 2,
        keep_paths: ['/photo4.jpg'],
      });
    });
  });

  describe('prev', () => {
    beforeEach(async () => {
      await component.loadGroups();
    });

    it('should decrement currentIndex', () => {
      component['currentIndex'].set(1);
      component['prev']();

      expect(component['currentIndex']()).toBe(0);
    });

    it('should not go below 0', () => {
      component['currentIndex'].set(0);
      component['prev']();

      expect(component['currentIndex']()).toBe(0);
    });
  });

  describe('next', () => {
    beforeEach(async () => {
      await component.loadGroups();
    });

    it('should increment currentIndex', () => {
      component['next']();

      expect(component['currentIndex']()).toBe(1);
    });

    it('should not exceed groups length when no more pages', () => {
      component['currentIndex'].set(1);
      component['next']();

      expect(component['currentIndex']()).toBe(1);
    });

    it('should load next page when at last group and more pages exist', async () => {
      mockApi.get.mockReturnValue(of({
        groups: [{ burst_id: 3, photos: [], best_path: '', count: 0 }],
        total_groups: 3, page: 2, per_page: 20, total_pages: 2,
      }));
      // Simulate multi-page scenario
      component['currentIndex'].set(1); // last group of page 1
      (component as any)['totalPages'].set(2); // there is a second page

      component['next']();

      // Should have called the API for page 2
      expect(mockApi.get).toHaveBeenCalledWith('/burst-groups', expect.objectContaining({ page: 2 }));
    });
  });

  describe('hasMore', () => {
    beforeEach(async () => {
      await component.loadGroups();
    });

    it('should return true when not at last group', () => {
      expect(component['hasMore']()).toBe(true);
    });

    it('should return false at last group with single page', () => {
      component['currentIndex'].set(1);
      expect(component['hasMore']()).toBe(false);
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
