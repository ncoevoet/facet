import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { CapsulesComponent } from './capsules.component';
import { I18N } from '../../core/i18n/keys';

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

  describe('load failures', () => {
    const lastPage = () => (mockApi.get.mock.calls.at(-1)![1] as { page: number }).page;
    const settle = () => vi.waitFor(() => expect(internals().loading()).toBe(false));

    it('re-requests the same page after a failed load-more, not the next one', async () => {
      // Let the regenerate effect's initial run happen before capsules exist.
      TestBed.tick();
      await internals().loadCapsules();
      TestBed.tick();
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('boom')));
      internals().loadMore();
      await settle();
      expect(lastPage()).toBe(2);

      internals().loadMore();
      await settle();
      expect(lastPage()).toBe(2);
    });

    it('flags a failed page-1 load as an error', async () => {
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('boom')));
      await internals().loadCapsules();
      expect(internals().loadError()).toBe(true);
      expect(internals().capsules()).toEqual([]);
      // Page-1 failures use the loadError banner — a toast would double the
      // notification.
      expect(mockSnackBar.open).not.toHaveBeenCalled();
    });

    it('clears stale pagination when a page-1 reload fails', async () => {
      await internals().loadCapsules();
      expect(internals().hasMore()).toBe(true);
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('boom')));
      internals().currentPage = 1;
      await internals().loadCapsules(true);
      // A hasMore left over from the earlier load would keep the scroll
      // sentinel alive and append page 2 onto the now-empty grid.
      expect(internals().hasMore()).toBe(false);
      expect(internals().total()).toBe(0);
      expect(internals().loadError()).toBe(true);
    });

    it('keeps the grid and sets no error when a later page fails', async () => {
      await internals().loadCapsules();
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('boom')));
      internals().loadMore();
      await settle();
      expect(internals().capsules().length).toBe(1);
      expect(internals().loadError()).toBe(false);
    });

    it('toasts the failure when a later page fails', async () => {
      await internals().loadCapsules();
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('boom')));
      internals().loadMore();
      await settle();
      // The grid holds earlier pages, so the loadError banner does not apply —
      // the failure must still be visible, as a toast.
      expect(mockSnackBar.open).toHaveBeenCalledWith(
        I18N.capsules.load_error, '', { duration: 3000 });
    });
  });

  describe('page-actions template', () => {
    it('adds no margin of its own: the shell wrapper and the bar already inset the first control to 16px', async () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          { provide: ApiService, useValue: mockApi },
          { provide: AuthService, useValue: mockAuth },
          { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
          { provide: MatSnackBar, useValue: mockSnackBar },
        ],
      });
      const fixture = TestBed.createComponent(CapsulesComponent);
      fixture.detectChanges();
      await fixture.whenStable();
      const template = TestBed.inject(HeaderSlotService).template()!;
      const view = template.createEmbeddedView({});
      view.detectChanges();
      const fields = view.rootNodes.flatMap((n: Node) => n instanceof Element ? Array.from(n.querySelectorAll('mat-form-field')).concat(n.matches('mat-form-field') ? [n] : []) : []);
      expect(fields.length).toBeGreaterThan(0);
      expect(fields.every(f => !f.classList.contains('ml-2'))).toBe(true);
      view.destroy();
    });
  });
});
