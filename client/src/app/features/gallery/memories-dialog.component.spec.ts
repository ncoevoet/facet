import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { MemoriesDialogComponent } from './memories-dialog.component';

describe('MemoriesDialogComponent', () => {
   
  let component: any;
  let mockApi: { get: jest.Mock };
  let mockRouter: { navigate: jest.Mock };
  let mockDialogRef: { close: jest.Mock };

  function createComponent(dialogData: Record<string, string> | null = null) {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        MemoriesDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: Router, useValue: mockRouter },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: dialogData },
      ],
    });
    component = TestBed.inject(MemoriesDialogComponent);
  }

  beforeEach(() => {
    mockApi = { get: jest.fn(() => of({ years: [], has_memories: false, date: '' })) };
    mockRouter = { navigate: jest.fn() };
    mockDialogRef = { close: jest.fn() };
  });

  describe('ngOnInit', () => {
    it('should load memories and populate years', async () => {
      const memoriesResponse = {
        years: [
          { year: '2023', photos: [{ path: '/p1.jpg', filename: 'p1.jpg', aggregate: 8.0, date_taken: '2023:06:15 10:00:00', date_formatted: 'June 15, 2023' }], total_count: 5 },
          { year: '2022', photos: [{ path: '/p2.jpg', filename: 'p2.jpg', aggregate: 7.0, date_taken: '2022:06:15 10:00:00', date_formatted: 'June 15, 2022' }], total_count: 3 },
        ],
        has_memories: true,
        date: '2024-06-15',
      };
      mockApi.get.mockReturnValue(of(memoriesResponse));
      createComponent();

      await component.ngOnInit();

      expect(component.years()).toHaveLength(2);
      expect(component.years()[0].year).toBe('2023');
      expect(component.loading()).toBe(false);
    });

    it('should pass date param when provided in dialog data', async () => {
      mockApi.get.mockReturnValue(of({ years: [], has_memories: false, date: '' }));
      createComponent({ date: '2024-06-15' });

      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/memories', { date: '2024-06-15' });
    });

    it('should not pass date param when dialog data is null', async () => {
      createComponent(null);

      await component.ngOnInit();

      expect(mockApi.get).toHaveBeenCalledWith('/memories', {});
    });

    it('should set years to empty on API error', async () => {
      mockApi.get.mockReturnValue(throwError(() => new Error('Server error')));
      createComponent();

      await component.ngOnInit();

      expect(component.years()).toEqual([]);
      expect(component.loading()).toBe(false);
    });

    it('should handle missing years in response', async () => {
      mockApi.get.mockReturnValue(of({ has_memories: false, date: '' }));
      createComponent();

      await component.ngOnInit();

      expect(component.years()).toEqual([]);
    });
  });

  describe('onPhotoClick', () => {
    beforeEach(() => {
      createComponent();
    });

    it('should close dialog and navigate to date filter', () => {
      const photo = {
        path: '/photo.jpg',
        filename: 'photo.jpg',
        aggregate: 8.0,
        date_taken: '2023:06:15 10:30:00',
        date_formatted: 'June 15, 2023',
      };

      component.onPhotoClick(photo);

      expect(mockDialogRef.close).toHaveBeenCalled();
      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          date_from: '2023-06-15',
          date_to: '2023-06-15',
        },
      });
    });

    it('should convert EXIF date format (colon-separated) to dash-separated', () => {
      const photo = {
        path: '/p.jpg',
        filename: 'p.jpg',
        aggregate: null,
        date_taken: '2022:12:25 08:00:00',
        date_formatted: '',
      };

      component.onPhotoClick(photo);

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], {
        queryParams: {
          date_from: '2022-12-25',
          date_to: '2022-12-25',
        },
      });
    });

    it('should not navigate when date_taken is empty', () => {
      const photo = {
        path: '/p.jpg',
        filename: 'p.jpg',
        aggregate: null,
        date_taken: '',
        date_formatted: '',
      };

      component.onPhotoClick(photo);

      expect(mockDialogRef.close).toHaveBeenCalled();
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });
  });
});
