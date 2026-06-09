import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { CapsulesComponent } from './capsules.component';

describe('CapsulesComponent', () => {
  let component: CapsulesComponent;
  let mockApi: { get: Mock };
  let mockAuth: { isEdition: Mock; isAuthenticated: Mock };
  let mockI18n: { t: Mock };
  let mockSnackBar: { open: Mock };

  const mockCapsulesResponse = {
    capsules: [
      {
        type: 'golden', id: 'c1', title: 'Golden', title_key: 'capsules.golden',
        title_params: {}, subtitle: '', cover_photo_path: '/a.jpg', photo_count: 10, icon: 'star',
      },
    ],
    total: 3,
    page: 1,
    per_page: 24,
    has_more: true,
  };

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(mockCapsulesResponse)) };
    mockAuth = { isEdition: vi.fn(() => true), isAuthenticated: vi.fn(() => true) };
    mockI18n = { t: vi.fn((key: string) => key) };
    mockSnackBar = { open: vi.fn() };

    TestBed.configureTestingModule({
      providers: [
        CapsulesComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
      ],
    });
    component = TestBed.inject(CapsulesComponent);
  });

  const internals = () => component as any;

  it('creates', () => {
    expect(component).toBeTruthy();
  });

  it('loads capsules from the API and sets pagination state', async () => {
    await internals().loadCapsules();
    expect(mockApi.get).toHaveBeenCalledWith(
      '/capsules',
      expect.objectContaining({ page: 1, per_page: 24 }),
    );
    expect(internals().capsules().length).toBe(1);
    expect(internals().total()).toBe(3);
    expect(internals().hasMore()).toBe(true);
  });

  it('loadMore advances the page and reloads when more are available', () => {
    internals().hasMore.set(true);
    internals().loading.set(false);
    internals().currentPage = 1;

    internals().loadMore();

    expect(internals().currentPage).toBe(2);
    expect(mockApi.get).toHaveBeenCalled();
  });
});
