import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { I18nService } from '../../../core/services/i18n.service';
import { ApiService } from '../../../core/services/api.service';
import { ShareDialogComponent, ShareDialogData } from './share-dialog.component';

describe('ShareDialogComponent', () => {
   
  let component: any;
  let mockApi: { post: Mock; get: Mock; delete: Mock };
  let mockDialogRef: { close: Mock };
  const status = signal({ owner: 'root' });
  const policy = { membership: 'manual', membership_can_change: true, downloads: 'album_member_original',
    photo_metadata: true, native_paths: true, manual_tags: false, saved_rules: false,
    password_protected: false, expires_at: null, proofing: false };

  function createComponent(data: ShareDialogData) {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [ShareDialogComponent],
      providers: [
        ShareDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: AuthService, useValue: { status, identity: () => 'root', isEdition: () => true, token: 'fixture-token' } },
        { provide: Router, useValue: { url: '/albums', events: new Subject() } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), currentLang: signal('en') } },
      ],
    });
    component = TestBed.inject(ShareDialogComponent);
  }

  beforeEach(() => {
    mockApi = {
      post: vi.fn(() => of({ share_url: '/shared/album/1?token=abc', share_token: 'abc' })),
      get: vi.fn(() => of({ sharing_policy: policy, total: 7 })),
      delete: vi.fn(() => of({})),
    };
    mockDialogRef = { close: vi.fn() };
    status.set({ owner: 'root' });
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
      expect(mockApi.get).toHaveBeenCalledWith('/shared/album/1', { token: 'abc', per_page: 1 });
      expect(component.policy()).toEqual(policy);
      expect(component.recipientCount()).toBe(7);
    });

    it('recovers policy with a read only request without regenerating a link', async () => {
      createComponent(albumData);
      mockApi.get.mockReturnValueOnce(throwError(() => new Error('offline')));
      await component.ngOnInit();
      expect(component.error()).toBe(true);
      expect(component.policy()).toBeNull();
      await component.readPolicy();
      expect(mockApi.post).toHaveBeenCalledTimes(1);
      expect(component.policy()).toEqual(policy);
      expect(component.error()).toBe(false);
    });

    it('renders the real recipient policy, optional metadata disclosure and safe recipient link', async () => {
      createComponent(albumData);
      const fixture = TestBed.createComponent(ShareDialogComponent);
      fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
      const root: HTMLElement = fixture.nativeElement;
      expect(root.textContent).toContain('albums.share_manual_scope');
      expect(root.textContent).toContain('albums.share_access_policy');
      expect(root.textContent).toContain('albums.share_proofing_off');
      const disclosure = root.querySelector('details')!;
      expect(disclosure.open).toBe(false);
      expect(disclosure.textContent).toContain('albums.share_metadata_disclosure');
      const link = root.querySelector('a')!;
      expect(link.getAttribute('href')).toContain('/shared/album/1?token=abc');
      expect(link.rel).toContain('noreferrer');
      expect(link.textContent).toContain('albums.open_recipient_view');
      fixture.destroy();
    });

    it('discards a prior-account link completion without reading recipient data', async () => {
      createComponent(albumData);
      const completion = new Subject<Record<string, unknown>>();
      mockApi.post.mockReturnValueOnce(completion);
      const pending = component.generateLink();
      status.set({ owner: 'other' });
      completion.next({ share_url: '/shared/album/1?token=old-owner' }); completion.complete();
      await pending;
      expect(component.shareUrl()).toBe('');
      expect(mockApi.get).not.toHaveBeenCalled();
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
      component.policy.set(policy);

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
      component.policy.set(policy);

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
