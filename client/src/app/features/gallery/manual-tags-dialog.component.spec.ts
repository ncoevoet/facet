import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { ManualTagsDialogComponent, ManualTagsDialogData } from './manual-tags-dialog.component';

describe('ManualTagsDialogComponent', () => {
  let component: ManualTagsDialogComponent;
  let mockDialogRef: { close: Mock; disableClose?: boolean };
  let mockApi: { post: Mock };

  function create(data: ManualTagsDialogData) {
    TestBed.resetTestingModule();
    mockDialogRef = { close: vi.fn() };
    mockApi = { post: vi.fn(() => of({ success: true, count: 2 })) };
    TestBed.configureTestingModule({
      providers: [
        ManualTagsDialogComponent,
        { provide: MatDialogRef, useValue: mockDialogRef },
        { provide: MAT_DIALOG_DATA, useValue: data },
        { provide: ApiService, useValue: mockApi },
      ],
    });
    component = TestBed.inject(ManualTagsDialogComponent);
  }

  const pathData: ManualTagsDialogData = { paths: ['/a.jpg', '/b.jpg'], count: 2 };

  it('initialises idle with an empty tag and the selection count', () => {
    create(pathData);

    expect(component.saving()).toBe(false);
    expect(component.tag()).toBe('');
    expect(component.data.count).toBe(2);
  });

  it('posts an add for the named paths and closes with the written count', async () => {
    create(pathData);
    component.tag.set('  trip ');

    await component.apply('add');

    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_manual_tags',
      { photo_paths: ['/a.jpg', '/b.jpg'], tag: 'trip', action: 'add' });
    expect(mockDialogRef.close).toHaveBeenCalledWith(2);
    expect(component.saving()).toBe(false);
  });

  it('posts a delete action for the remove button', async () => {
    create(pathData);
    component.tag.set('trip');

    await component.apply('delete');

    expect(mockApi.post.mock.calls[0][1].action).toBe('delete');
  });

  it('sends the filter and exclusions, not a path list, for a whole-view selection', async () => {
    create({ paths: [], filters: { tag: 'x' }, exclude: ['/c.jpg'], count: 5000 });
    component.tag.set('trip');

    await component.apply('add');

    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_manual_tags',
      { filters: { tag: 'x' }, exclude: ['/c.jpg'], tag: 'trip', action: 'add' });
  });

  it('splits a long path list into chunks of at most 1000 and sums the counts', async () => {
    const paths = Array.from({ length: 2500 }, (_, i) => `/p${i}.jpg`);
    create({ paths, count: 2500 });
    component.tag.set('trip');

    await component.apply('add');

    expect(mockApi.post).toHaveBeenCalledTimes(3);
    expect(mockApi.post.mock.calls[2][1].photo_paths).toHaveLength(500);
    expect(mockDialogRef.close).toHaveBeenCalledWith(6);
  });

  it('does nothing for a blank tag', async () => {
    create(pathData);
    component.tag.set('   ');

    await component.apply('add');

    expect(mockApi.post).not.toHaveBeenCalled();
    expect(mockDialogRef.close).not.toHaveBeenCalled();
  });

  it('sets saving while the request is in flight', async () => {
    create(pathData);
    component.tag.set('trip');
    let during = false;
    mockApi.post.mockImplementation(() => { during = component.saving(); return of({ count: 1 }); });

    await component.apply('add');

    expect(during).toBe(true);
  });

  it('stays open and reports an error when the server refuses', async () => {
    create(pathData);
    component.tag.set('bad');
    mockApi.post.mockReturnValue(throwError(() => new Error('422')));

    await component.apply('add');

    expect(mockDialogRef.close).not.toHaveBeenCalled();
    expect(component.failed()).toBe(true);
    expect(component.saving()).toBe(false);
    expect(mockDialogRef.disableClose).toBeUndefined();
  });

  it('does not submit on Enter while a save is in flight', async () => {
    create(pathData);
    component.tag.set('trip');
    component.saving.set(true);

    await component.apply('add');

    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('cancel after a partial failure closes with the committed count so the caller reloads', async () => {
    create({ paths: Array.from({ length: 1500 }, (_, i) => `/p${i}.jpg`), count: 1500 });
    component.tag.set('trip');
    mockApi.post
      .mockReturnValueOnce(of({ count: 1000 }))
      .mockReturnValueOnce(throwError(() => new Error('boom')));

    await component.apply('add');
    expect(mockDialogRef.disableClose).toBe(true);
    component.cancel();

    expect(component.failed()).toBe(true);
    expect(mockDialogRef.close).toHaveBeenCalledWith(1000);
  });

  it('cancel with nothing committed closes with no result', () => {
    create(pathData);

    component.cancel();

    expect(mockDialogRef.close).toHaveBeenCalledWith(undefined);
  });
});
