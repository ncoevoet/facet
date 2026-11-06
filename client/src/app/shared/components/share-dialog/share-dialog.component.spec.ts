import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { ShareDialogComponent, ShareDialogData } from './share-dialog.component';

describe('ShareDialogComponent', () => {
   
  let component: any;
  let mockApi: { post: Mock; get: Mock; delete: Mock };
  let mockDialogRef: { close: Mock };

  function createComponent(data: ShareDialogData) {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        ShareDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    component = TestBed.inject(ShareDialogComponent);
  }

  beforeEach(() => {
    mockApi = {
      post: vi.fn(() => of({ share_url: '/shared/album/1?token=abc', share_token: 'abc' })),
      get: vi.fn(() => of({ token: 'xyz' })),
      delete: vi.fn(() => of({})),
    };
    mockDialogRef = { close: vi.fn() };
  });

  describe('album sharing', () => {
    const albumData: ShareDialogData = {
      entityType: 'album',
      entityId: 1,
      autoGenerate: true,
      i18nPrefix: 'albums',
      generateApi: {
        method: 'post',
        url: '/api/albums/1/share',
        body: {},
        extractUrl: (res: Record<string, unknown>) => res['share_url'] as string,
      },
      revokeApi: { url: '/api/albums/1/share' },
    };

    it('should auto-generate link when autoGenerate is true', async () => {
      createComponent(albumData);

      await component.ngOnInit();

      expect(mockApi.post).toHaveBeenCalledWith('/api/albums/1/share', {});
      expect(component.shareUrl()).toBe('/shared/album/1?token=abc');
    });

    it('should not generate link when autoGenerate is false', async () => {
      createComponent({ ...albumData, autoGenerate: false });

      await component.ngOnInit();

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(component.shareUrl()).toBe('');
    });

    it('should call POST and set shareUrl on generateLink', async () => {
      createComponent({ ...albumData, entityId: 5, generateApi: { ...albumData.generateApi, url: '/api/albums/5/share' }, autoGenerate: false });

      await component.generateLink();

      expect(mockApi.post).toHaveBeenCalledWith('/api/albums/5/share', {});
      expect(component.shareUrl()).toBe('/shared/album/1?token=abc');
      expect(component.loading()).toBe(false);
    });

    it('should set loading true then false during generateLink', async () => {
      createComponent({ ...albumData, autoGenerate: false });

      const promise = component.generateLink();
      expect(component.loading()).toBe(true);

      await promise;
      expect(component.loading()).toBe(false);
    });

    it('should call DELETE and close dialog with revoked on revoke', async () => {
      createComponent({ ...albumData, entityId: 3, revokeApi: { url: '/api/albums/3/share' } });
      component.shareUrl.set('/shared/album/3?token=abc');

      await component.revoke();

      expect(mockApi.delete).toHaveBeenCalledWith('/api/albums/3/share');
      expect(component.shareUrl()).toBe('');
      expect(mockDialogRef.close).toHaveBeenCalledWith('revoked');
    });

    it('should set the error when generateLink fails', async () => {
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      createComponent({ ...albumData, autoGenerate: false });

      await component.generateLink();

      expect(component.error()).toBe('errors.action_failed');
      expect(component.shareUrl()).toBe('');
      expect(component.loading()).toBe(false);
    });

    it('should keep the dialog open and show the error when revoke fails', async () => {
      mockApi.delete.mockReturnValue(throwError(() => new Error('boom')));
      createComponent(albumData);
      component.shareUrl.set('/shared/album/1?token=abc');

      await component.revoke();

      expect(component.error()).toBe('errors.action_failed');
      expect(component.shareUrl()).toBe('/shared/album/1?token=abc');
      expect(mockDialogRef.close).not.toHaveBeenCalled();
    });
  });

  describe('fullShareUrl', () => {
    it('should prepend window.location.origin to shareUrl', () => {
      createComponent({
        entityType: 'album',
        entityId: 1,
        autoGenerate: false,
        i18nPrefix: 'albums',
        generateApi: { method: 'post', url: '/api/albums/1/share', body: {}, extractUrl: (res: Record<string, unknown>) => res['share_url'] as string },
      });
      component.shareUrl.set('/shared/album/1?token=xyz');

      expect(component.fullShareUrl()).toBe(`${window.location.origin}/shared/album/1?token=xyz`);
    });
  });

  describe('copyLink', () => {
    it('should copy full URL to clipboard', async () => {
      createComponent({
        entityType: 'album',
        entityId: 1,
        autoGenerate: false,
        i18nPrefix: 'albums',
        generateApi: { method: 'post', url: '/api/albums/1/share', body: {}, extractUrl: (res: Record<string, unknown>) => res['share_url'] as string },
      });
      component.shareUrl.set('/shared/album/1?token=abc');

      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, { clipboard: { writeText } });

      await component.copyLink();

      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('/shared/album/1?token=abc'));
      expect(component.copied()).toBe(true);
    });

    it('should reset copied after timeout', async () => {
      vi.useFakeTimers();
      createComponent({
        entityType: 'album',
        entityId: 1,
        autoGenerate: false,
        i18nPrefix: 'albums',
        generateApi: { method: 'post', url: '/api/albums/1/share', body: {}, extractUrl: (res: Record<string, unknown>) => res['share_url'] as string },
      });
      component.shareUrl.set('/shared/album/1?token=abc');

      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, { clipboard: { writeText } });

      await component.copyLink();
      expect(component.copied()).toBe(true);

      vi.advanceTimersByTime(2000);
      expect(component.copied()).toBe(false);

      vi.useRealTimers();
    });
  });
});
