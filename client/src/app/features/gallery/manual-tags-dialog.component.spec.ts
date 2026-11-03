import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { observeManualTags } from './manual-tag-observation.util';
import { ApiService } from '../../core/services/api.service';
import { ManualTagsDialogComponent, ManualTagsDialogScope } from './manual-tags-dialog.component';

describe('ManualTagsDialogComponent', () => {
  let component: ManualTagsDialogComponent;
  let mockDialogRef: { close: Mock; beforeClosed: () => Subject<unknown>; disableClose?: boolean };
  let mockApi: { post: Mock };
  let settled: Mock;
  let closing: Subject<unknown>;
  const owner = signal('alice');
  const edition = signal(true);
  const status = signal({ session: 1 });
  const token = signal('fixture-token');

  function create(data: ManualTagsDialogScope) {
    TestBed.resetTestingModule();
    owner.set('alice'); edition.set(true);
    status.set({ session: 1 }); token.set('fixture-token');
    closing = new Subject<unknown>();
    settled = vi.fn();
    mockDialogRef = { close: vi.fn(() => closing.next(undefined)), beforeClosed: () => closing };
    mockApi = { post: vi.fn(() => of({ success: true, count: 2 })) };
    TestBed.configureTestingModule({
      providers: [
        ManualTagsDialogComponent,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: { ...data, onSettled: settled } },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: { identity: owner, isEdition: edition, status, get token() { return token(); } } },
        { provide: I18nService, useValue: { translations: signal({}), t: (key: string, vars?: Record<string, unknown>) => key + (vars ? ' ' + Object.values(vars).join(' ') : '') } },
      ],
    });
    component = TestBed.inject(ManualTagsDialogComponent);
  }

  const pathData: ManualTagsDialogScope = { paths: ['/a.jpg', '/b.jpg'], count: 2 };

  it('captures a replacement list before Apply and preserves its target after input changes', async () => {
    create(pathData); component.tag.set('trip\nfamily'); component.preview('replace');
    component.tag.set('later'); component.data.paths.push('/later.jpg');
    expect(mockApi.post).not.toHaveBeenCalled();
    await component.apply();
    expect(mockApi.post).toHaveBeenCalledExactlyOnceWith('/photos/batch_manual_tags', {
      photo_paths: ['/a.jpg', '/b.jpg'], action: 'replace', tags: ['trip', 'family'],
    });
  });

  it('requires an explicit clear preview and does not send ignored tag values', async () => {
    create(pathData); component.tag.set('ignored'); component.preview('clear');
    expect(mockApi.post).not.toHaveBeenCalled();
    await component.apply();
    expect(mockApi.post).toHaveBeenCalledExactlyOnceWith('/photos/batch_manual_tags', {
      photo_paths: ['/a.jpg', '/b.jpg'], action: 'clear',
    });
  });

  it.each(['too,long', 'x'.repeat(65), 'bad\u0001value', 'bad\u200bvalue'])(
    'refuses to preview an invalid tag', value => {
      create(pathData); component.tag.set(value); component.preview('add');
      expect(component.plan()).toBeNull();
      expect(mockApi.post).not.toHaveBeenCalled();
    },
  );

  it('allows editing after a definite validation failure, but not after an uncertain write', async () => {
    create(pathData); component.tag.set('trip'); component.preview('add');
    mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 422 })));
    await component.apply(); component.edit();
    expect(component.plan()).toBeNull(); expect(component.failed()).toBe(false);
    component.preview('add'); mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 0 })));
    await component.apply(); component.edit();
    expect(component.uncertain()).toBe(true); expect(component.plan()).not.toBeNull();
  });

  it('refuses to replay an uncertain replacement over potentially newer tags', async () => {
    create(pathData); component.tag.set('trip'); component.preview('replace');
    mockApi.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 0 })));
    await component.apply(); await component.apply();
    expect(component.uncertain()).toBe(true);
    expect(mockApi.post).toHaveBeenCalledOnce();
    component.cancel();
    expect(mockDialogRef.close).toHaveBeenCalledWith(expect.objectContaining({ action: 'replace', uncertain: true }));
  });

  it('stops replacement chunks after token rotation while preserving the confirmed receipt', async () => {
    create({ paths: Array.from({ length: 1001 }, (_, i) => `/p${i}.jpg`), count: 1001 });
    const response = new Subject<{ count: number }>(); mockApi.post.mockReturnValue(response);
    component.tag.set('new'); component.preview('replace'); const work = component.apply();
    token.set('rotated'); response.next({ count: 1000 }); response.complete(); await work;
    expect(mockApi.post).toHaveBeenCalledOnce();
    expect(settled).toHaveBeenCalledWith(expect.objectContaining({ confirmedCount: 1000, incomplete: true }));
  });

  it('initialises idle with an empty tag and the selection count', () => {
    create(pathData);

    expect(component.saving()).toBe(false);
    expect(component.tag()).toBe('');
    expect(component.data.count).toBe(2);
  });

  it('posts an add for the named paths and closes with the written count', async () => {
    create(pathData);
    component.tag.set('  trip ');

    component.preview('add');
    await component.apply();

    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_manual_tags',
      { photo_paths: ['/a.jpg', '/b.jpg'], tag: 'trip', action: 'add' });
    expect(mockDialogRef.close).toHaveBeenCalledWith({ confirmedCount: 2, action: 'add', tag: 'trip', incomplete: false, uncertain: false });
    expect(component.saving()).toBe(false);
  });

  it('posts a delete action for the remove button', async () => {
    create(pathData);
    component.tag.set('trip');

    component.preview('delete');
    await component.apply();

    expect(mockApi.post.mock.calls[0][1].action).toBe('delete');
  });

  it('sends the captured matching list for a whole-view selection', async () => {
    create({ paths: ['/a.jpg', '/b.jpg'], fromWholeView: true, count: 2 });
    component.tag.set('trip');

    component.preview('add');
    await component.apply();

    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_manual_tags',
      { photo_paths: ['/a.jpg', '/b.jpg'], tag: 'trip', action: 'add' });
  });

  it('splits a long path list into chunks of at most 1000 and sums the counts', async () => {
    const paths = Array.from({ length: 2500 }, (_, i) => `/p${i}.jpg`);
    create({ paths, count: 2500 });
    component.tag.set('trip');

    component.preview('add');
    await component.apply();

    expect(mockApi.post).toHaveBeenCalledTimes(3);
    expect(mockApi.post.mock.calls[2][1].photo_paths).toHaveLength(500);
    expect(mockDialogRef.close).toHaveBeenCalledWith({ confirmedCount: 6, action: 'add', tag: 'trip', incomplete: false, uncertain: false });
  });

  it('does nothing for a blank tag', async () => {
    create(pathData);
    component.tag.set('   ');

    component.preview('add');
    await component.apply();

    expect(mockApi.post).not.toHaveBeenCalled();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  it('sets saving while the request is in flight', async () => {
    create(pathData);
    component.tag.set('trip');
    let during = false;
    mockApi.post.mockImplementation(() => { during = component.saving(); return of({ count: 1 }); });

    component.preview('add');
    await component.apply();

    expect(during).toBe(true);
  });

  it('stays open and reports an error when the server refuses', async () => {
    create(pathData);
    component.tag.set('bad');
    mockApi.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 422 })));

    component.preview('add');
    await component.apply();

    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.failed()).toBe(true);
    expect(component.saving()).toBe(false);
    expect(mockDialogRef.disableClose).toBeUndefined();
  });

  it('does not submit on Enter while a save is in flight', async () => {
    create(pathData);
    component.tag.set('trip');
    component.saving.set(true);

    component.preview('add');
    await component.apply();

    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('cancel after a partial failure closes with the committed count so the caller reloads', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    component.tag.set('trip');
    mockApi.post
      .mockReturnValueOnce(of({ count: 1000 }))
      .mockReturnValueOnce(throwError(() => new Error('boom')));

    component.preview('add');
    await component.apply();
    expect(mockDialogRef.disableClose).toBe(true);
    component.cancel();

    expect(component.failed()).toBe(true);
    expect(mockDialogRef.close).toHaveBeenCalledWith({ confirmedCount: 1000, action: 'add', tag: 'trip', incomplete: true, uncertain: true });
  });

  it('cancel with nothing committed closes with no result', () => {
    create(pathData);

    component.cancel();

    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
  });
  it('previews without writing and freezes the tag, action and target for Apply', async () => {
    const data = { paths: ['/a.jpg', '/b.jpg'], fromWholeView: true, count: 2 };
    create(data);
    component.tag.set('trip');
    component.preview('add');
    expect(mockApi.post).not.toHaveBeenCalled();
    data.paths.push('/outside');
    component.data.paths.push('/changed');
    component.tag.set('different');
    component.preview('delete');
    await component.apply();
    expect(mockApi.post).toHaveBeenCalledExactlyOnceWith('/photos/batch_manual_tags', { photo_paths: ['/a.jpg', '/b.jpg'], tag: 'trip', action: 'add' });
  });

  it('requires an explicit preview before any write', async () => {
    create(pathData);
    component.tag.set('trip');
    await component.apply();
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('retries only the failed and remaining chunks with the captured operation', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    component.tag.set('trip'); component.preview('add');
    mockApi.post.mockReturnValueOnce(of({ count: 1000 })).mockReturnValueOnce(throwError(() => new Error('lost'))).mockReturnValueOnce(of({ count: 500 }));
    await component.apply();
    component.tag.set('other'); component.preview('delete');
    await component.apply();
    expect(mockApi.post).toHaveBeenCalledTimes(3);
    expect(mockApi.post.mock.calls[2][1]).toEqual({ photo_paths: Array.from({ length: 500 }, (_, i) => `/p${i + 1000}.jpg`), tag: 'trip', action: 'add' });
    expect(mockDialogRef.close).toHaveBeenCalledWith({ confirmedCount: 1500, tag: 'trip', action: 'add', incomplete: false, uncertain: true });
  });

  it('blocks close during a request and stops later chunks after an identity change', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    const response = new Subject<{ count: number }>();
    mockApi.post.mockReturnValue(response);
    component.tag.set('trip'); component.preview('add');
    const pending = component.apply();
    expect(mockDialogRef.disableClose).toBe(true);
    component.cancel();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    owner.set('bob');
    response.next({ count: 1000 });
    await pending;
    TestBed.flushEffects();
    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
  });

  it('settles a sent request after close starts without starting another chunk', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    const response = new Subject<{ count: number }>();
    mockApi.post.mockReturnValue(response);
    component.tag.set('trip'); component.preview('add');
    const pending = component.apply();
    closing.next(undefined);
    response.next({ count: 1000 });
    await pending;
    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(settled).toHaveBeenCalledExactlyOnceWith({ confirmedCount: 1000, tag: 'trip', action: 'add', incomplete: true, uncertain: false });
  });

  it('latches permission loss until the sent request settles even after unlocking again', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    const response = new Subject<{ count: number }>();
    mockApi.post.mockReturnValue(response);
    component.tag.set('trip'); component.preview('add');
    const pending = component.apply();
    edition.set(false); TestBed.flushEffects();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
    edition.set(true); TestBed.flushEffects();
    response.next({ count: 1000 });
    await pending; TestBed.flushEffects();
    expect(mockApi.post).toHaveBeenCalledTimes(1);
    const receipt = { confirmedCount: 1000, tag: 'trip', action: 'add', incomplete: true, uncertain: false };
    expect(settled).toHaveBeenCalledExactlyOnceWith(receipt);
    expect(mockDialogRef.close).toHaveBeenCalledWith(receipt);
  });

  it('settles an unknown outcome after permission loss even without confirmed writes', async () => {
    create(pathData);
    const response = new Subject<{ count: number }>();
    mockApi.post.mockReturnValue(response);
    component.tag.set('trip'); component.preview('add');
    const pending = component.apply();
    edition.set(false); TestBed.flushEffects();
    response.error(new HttpErrorResponse({ status: 0 }));
    await pending; TestBed.flushEffects();
    const receipt = { confirmedCount: 0, tag: 'trip', action: 'add', incomplete: true, uncertain: true };
    expect(settled).toHaveBeenCalledExactlyOnceWith(receipt);
    expect(mockDialogRef.close).toHaveBeenCalledWith(receipt);
  });

  it('returns an uncertain receipt even if no response confirmed a count', async () => {
    create(pathData); component.tag.set('trip'); component.preview('add');
    mockApi.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 0 })));
    await component.apply(); component.cancel();
    expect(mockDialogRef.close).toHaveBeenCalledWith({ confirmedCount: 0, tag: 'trip', action: 'add', incomplete: true, uncertain: true });
  });

  it('summarizes common and partial manual tags without counting a duplicate twice', () => {
    expect(observeManualTags([{ manual_tags: ['shared', 'a', 'a'] }, { manual_tags: ['shared', 'b'] }])).toEqual({ photos: 2, tags: [{ tag: 'shared', count: 2 }, { tag: 'a', count: 1 }, { tag: 'b', count: 1 }], overflow: 0 });
  });

  it('renders an Add preview and only writes after the separate Apply button', async () => {
    create(pathData);
    const fixture = TestBed.createComponent(ManualTagsDialogComponent);
    component = fixture.componentInstance;
    component.tag.set('trip');
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const add = [...root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes('manual_tags.add_action'))!;
    add.click(); fixture.detectChanges();
    expect(root.querySelector('[data-tag-preview]')?.textContent).toContain('trip');
    expect(root.querySelector('[data-tag-target]')?.textContent).toContain('2');
    expect(mockApi.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-apply-tags]')!.click();
    await fixture.whenStable();
    expect(mockApi.post).toHaveBeenCalledOnce();
  });

});
