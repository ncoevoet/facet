import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { ApiService } from '../../core/services/api.service';
import { PersonAssignmentHistoryService } from '../../core/services/person-assignment-history.service';
import { AuthService } from '../../core/services/auth.service';
import {
  dragBox,
  ManualFaceDialogComponent,
  ManualFaceRegion,
} from './manual-face-dialog.component';
describe('manual face editor', () => {
  const region: ManualFaceRegion = {
    id: 3,
    manual_key: 'key',
    bbox: [0.1, 0.2, 0.8, 0.9],
    person_id: 5,
    person_name: 'Ada',
    source_changed: false,
  };
  let component: ManualFaceDialogComponent;
  let api: {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    put: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
  let committed: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    api = {
      get: vi.fn(() => of({ regions: [] })),
      post: vi.fn(() => of(region)),
      put: vi.fn(() => of(region)),
      delete: vi.fn(() => of({ success: true })),
    };
    committed = vi.fn(async () => {});
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { identity: () => '1|test', isEdition: () => true } },
        ManualFaceDialogComponent,
        {
          provide: MAT_DIALOG_DATA,
          useValue: { path: '/a.raw', filename: 'a.raw', onCommitted: committed },
        },
        { provide: ApiService, useValue: api },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: I18nService, useValue: { translations: () => ({}), t: (key: string) => key } },
      ],
    });
    component = TestBed.inject(ManualFaceDialogComponent);
    component.frame.set({ image_base64: 'jpeg', width: 100, height: 200, frame_token: 'token' });
    component.bbox.set([0.1, 0.2, 0.8, 0.9]);
    component.person.set({ person_id: 5 });
  });
  it('saves a face on HTTP LAN without randomUUID', async () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    try {
      await component.save();
      expect(api.post).toHaveBeenCalledWith('/photo/manual-faces', expect.objectContaining({
        client_id: expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
      }));
      expect(committed).toHaveBeenCalled();
    } finally { vi.unstubAllGlobals(); }
  });

  it.each(['face', 'object'] as const)('refuses %s deletion from a previous account', async kind => {
    vi.spyOn(TestBed.inject(AuthService), 'identity').mockReturnValue('1|other');
    if (kind === 'face') await component.remove(region);
    else await component.removeObject({ id: 9, label: 'cake', box: [0.1, 0.2, 0.8, 0.9] });
    expect(api.delete).not.toHaveBeenCalled();
    expect(committed).not.toHaveBeenCalled();
  });

  it.each(['face', 'object'] as const)('ignores a late %s deletion after the account changes', async kind => {
    const response = new Subject<{ success: boolean }>();
    api.delete.mockReturnValue(response);
    const object = { id: 9, label: 'cake', box: [0.1, 0.2, 0.8, 0.9] };
    component.regions.set([region]); component.objects.set([object]);
    const changed = vi.fn();
    component.data.onObjectsChanged = changed;
    const pending = kind === 'face' ? component.remove(region) : component.removeObject(object);
    vi.spyOn(TestBed.inject(AuthService), 'identity').mockReturnValue('1|other');
    response.next({ success: true }); response.complete();
    await pending;
    expect(component.regions()).toEqual([region]);
    expect(component.objects()).toEqual([object]);
    expect(committed).not.toHaveBeenCalled(); expect(changed).not.toHaveBeenCalled();
  });

  it('warns for overlapping boxes of the same person, excluding self and other people', () => {
    component.regions.set([region]);
    expect(component.overlappingPersonBox()).toBe(true);
    component.edit(region);
    expect(component.overlappingPersonBox()).toBe(false);
    component.newRegion();
    component.person.set({ person_id: 5 });
    component.bbox.set([0.2, 0.3, 0.4, 0.5]);
    expect(component.overlappingPersonBox()).toBe(true);
    component.person.set({ person_id: 6 });
    expect(component.overlappingPersonBox()).toBe(false);
    component.person.set({ person_id: 5 });
    component.bbox.set([0.8, 0.2, 1, 0.9]);
    expect(component.overlappingPersonBox()).toBe(false);
    component.bbox.set([0.2, 0.3, 0.4, 0.5]);
    component.regions.set([{ ...region, source_changed: true }]);
    expect(component.overlappingPersonBox()).toBe(false);
  });
  it('records the committed resolved person ID, including newly created people', async () => {
    const record = vi.spyOn(TestBed.inject(PersonAssignmentHistoryService), 'record');
    component.person.set({ new_person_name: 'Ada' });
    await component.save();
    expect(record).toHaveBeenCalledWith(5, '1|test');
  });
  it('does not promote a failed save or update a new owner from a late save', async () => {
    const record = vi.spyOn(TestBed.inject(PersonAssignmentHistoryService), 'record');
    api.post.mockReturnValueOnce(throwError(() => new Error('failed')));
    await component.save();
    expect(record).not.toHaveBeenCalled();
    const response = new Subject<ManualFaceRegion>();
    api.post.mockReturnValueOnce(response);
    const saving = component.save();
    vi.spyOn(TestBed.inject(AuthService), 'identity').mockReturnValue('1|other');
    response.next(region);
    response.complete();
    await saving;
    expect(component.regions()).toEqual([]);
    expect(committed).not.toHaveBeenCalled();
    expect(TestBed.inject(PersonAssignmentHistoryService).recentIds()).toEqual([]);
  });
  it('requires re-marking a cached region after preview reload', async () => {
    component.regions.set([region]);
    api.get.mockImplementation((path: string) =>
      of(
        path.endsWith('frame')
          ? { image_base64: 'fresh', width: 100, height: 200, frame_token: 'fresh' }
          : { regions: [region] },
      ),
    );
    await component.reloadFrame();
    component.edit(region);
    await component.save();
    expect(api.put).not.toHaveBeenCalled();
    component.setCoordinate(0, 20);
    await component.save();
    expect(api.put).toHaveBeenCalledOnce();
  });
  it('requires re-marking a late list response from before the refreshed frame', async () => {
    const list = new Subject<{ regions: ManualFaceRegion[] }>();
    api.get.mockImplementation((path: string) =>
      path.endsWith('frame')
        ? of({ image_base64: 'fresh', width: 100, height: 200, frame_token: 'fresh' })
        : list,
    );
    const pending = component.reloadFrame();
    await Promise.resolve();
    list.next({ regions: [region] });
    list.complete();
    await pending;
    component.edit(region);
    await component.save();
    expect(api.put).not.toHaveBeenCalled();
  });
  it('retains list failure after a later frame success and retries the list', async () => {
    const frame = new Subject<{
      image_base64: string;
      width: number;
      height: number;
      frame_token: string;
    }>();
    api.get.mockImplementation((path: string) =>
      path.endsWith('frame') ? frame : throwError(() => new Error('list offline')),
    );
    const pending = component.load();
    frame.next({ image_base64: 'fresh', width: 100, height: 200, frame_token: 'fresh' });
    frame.complete();
    await pending;
    expect(component.listFailed()).toBe(true);
    expect(component.listLoaded()).toBe(false);
    api.get.mockImplementation((path: string) =>
      of(
        path.endsWith('frame')
          ? { image_base64: 'fresh', width: 100, height: 200, frame_token: 'fresh' }
          : { regions: [region] },
      ),
    );
    await component.reloadFrame();
    expect(component.listFailed()).toBe(false);
    expect(component.regions()).toEqual([region]);
  });
  it('keeps empty numeric edges invalid without moving the box or clearing stale review', async () => {
    component.edit({ ...region, source_changed: true });
    component.setCoordinate(0, null);
    component.setCoordinate(1, null);
    expect(component.bbox()).toEqual(region.bbox);
    expect(component.needsRemark()).toBe(true);
    expect(component.percentages()[0]).toBeNull();
    await component.save();
    expect(api.put).not.toHaveBeenCalled();
    component.setCoordinate(0, 10);
    await component.save();
    expect(api.put).not.toHaveBeenCalled();
    component.setCoordinate(1, 20);
    await component.save();
    expect(api.put).toHaveBeenCalledOnce();
  });
  it('rounds display percentages without rounding authoritative geometry', () => {
    component.bbox.set([0.09999999999999998, 0.2, 0.8, 0.9]);
    expect(component.percentages()[0]).toBe(10);
    expect(component.bbox()[0]).toBe(0.09999999999999998);
  });
  it('renders the overlap warning while permitting save and clears it after a native coordinate edit', async () => {
    api.get.mockImplementation((path: string) => of(path.endsWith('frame')
      ? { image_base64: 'jpeg', width: 100, height: 200, frame_token: 'frame' }
      : { regions: [region] }));
    const view = TestBed.createComponent(ManualFaceDialogComponent);
    const editor = view.componentInstance;
    view.detectChanges();
    await view.whenStable();
    editor.person.set({ person_id: 5 });
    [20, 30, 40, 50].forEach((value, index) => editor.setCoordinate(index, value));
    view.detectChanges();
    expect(view.nativeElement.textContent).toContain('manual_faces.same_person_overlap');
    const save = Array.from(view.nativeElement.querySelectorAll('button')).find(
      (button: any) => button.textContent.includes('ui.buttons.save')) as HTMLButtonElement;
    view.detectChanges();
    expect(save.disabled).toBe(false);
    const inputs = view.nativeElement.querySelectorAll('input[type=number]') as NodeListOf<HTMLInputElement>;
    inputs[2].value = '95';
    inputs[2].dispatchEvent(new Event('input'));
    inputs[0].value = '90';
    inputs[0].dispatchEvent(new Event('input'));
    view.detectChanges();
    await view.whenStable();
    expect(view.nativeElement.textContent).not.toContain('manual_faces.same_person_overlap');
    view.detectChanges();
    expect(save.disabled).toBe(false);
  });
  it('renders saved-list failure without falsely presenting an empty successful list', () => {
    const view = TestBed.createComponent(ManualFaceDialogComponent);
    vi.spyOn(view.componentInstance, 'ngOnInit').mockImplementation(() => {});
    view.componentInstance.listFailed.set(true);
    view.detectChanges();
    expect(view.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'errors.action_failed',
    );
    expect(view.nativeElement.textContent).not.toContain('manual_faces.empty');
    view.componentInstance.listFailed.set(false);
    view.componentInstance.listLoaded.set(true);
    view.detectChanges();
    expect(view.nativeElement.textContent).toContain('manual_faces.empty');
  });
  it('preserves an empty numeric field from the actual Angular value accessor', async () => {
    const view = TestBed.createComponent(ManualFaceDialogComponent);
    vi.spyOn(view.componentInstance, 'ngOnInit').mockImplementation(() => {});
    view.componentInstance.frame.set({
      image_base64: 'jpeg',
      width: 100,
      height: 200,
      frame_token: 'frame',
    });
    view.componentInstance.edit({ ...region, source_changed: true });
    view.detectChanges();
    await view.whenStable();
    const input = view.nativeElement.querySelector('input[type=number]') as HTMLInputElement;
    input.value = '';
    input.dispatchEvent(new Event('input'));
    view.detectChanges();
    await view.whenStable();
    expect(input.value).toBe('');
    expect(view.componentInstance.valid()).toBe(false);
    expect(view.componentInstance.bbox()).toEqual(region.bbox);
    expect(view.componentInstance.needsRemark()).toBe(true);
  });
  it('renders the canonical preview and labeled numeric keyboard alternative', () => {
    const view = TestBed.createComponent(ManualFaceDialogComponent);
    vi.spyOn(view.componentInstance, 'ngOnInit').mockImplementation(() => {});
    view.componentInstance.frame.set({
      image_base64: 'canonicalJPEG',
      width: 100,
      height: 200,
      frame_token: 'frame',
    });
    view.detectChanges();
    const image = view.nativeElement.querySelector('img') as HTMLImageElement;
    expect(image.getAttribute('src')).toBe('data:image/jpeg;base64,canonicalJPEG');
    expect(image.classList.contains('max-h-[45vh]')).toBe(true);
    const numbers = view.nativeElement.querySelectorAll('label input[type=number]');
    expect(numbers).toHaveLength(4);
    expect(numbers[0].parentElement.textContent).toContain('manual_faces.left');
    numbers[0].value = '25';
    numbers[0].dispatchEvent(new Event('input'));
    view.detectChanges();
    expect(view.componentInstance.bbox()[0]).toBe(0.25);
  });
  it('uses the shared person picker as a proposal and creates nobody until Save', async () => {
    const picker = TestBed.inject(MatDialog);
    vi.mocked(picker.open).mockReturnValue({
      afterClosed: () => of({ kind: 'create', name: 'Grace' }),
    } as never);
    await component.choosePerson();
    expect(component.person()).toEqual({ new_person_name: 'Grace' });
    expect(api.post).not.toHaveBeenCalled();
    await component.save();
    expect(api.post).toHaveBeenCalledWith(
      '/photo/manual-faces',
      expect.objectContaining({ new_person_name: 'Grace' }),
    );
  });
  it('preserves the previous person when the picker is cancelled', async () => {
    vi.mocked(TestBed.inject(MatDialog).open).mockReturnValue({
      afterClosed: () => of(null),
    } as never);
    await component.choosePerson();
    expect(component.person()).toEqual({ person_id: 5 });
    expect(api.post).not.toHaveBeenCalled();
  });
  it('normalizes reverse drag and clamps to actual image bounds', () => {
    expect(dragBox([0.8, 0.9], [-0.2, 1.2])).toEqual([0, 0.9, 0.8, 1]);
  });
  it('guides detected overlap to existing face assignment while retaining the draft', async () => {
    api.post.mockReturnValue(
      throwError(
        () =>
          new HttpErrorResponse({
            status: 409,
            error: { detail: { code: 'detected_face_overlap' } },
          }),
      ),
    );
    await component.save();
    expect(component.error()).toBe('manual_faces.detected_overlap');
    expect(component.bbox()).toEqual([0.1, 0.2, 0.8, 0.9]);
    expect(component.person()).toEqual({ person_id: 5 });
    expect(committed).not.toHaveBeenCalled();
  });
  it('keeps unknown error codes on generic translated save guidance', async () => {
    api.post.mockReturnValue(
      throwError(
        () =>
          new HttpErrorResponse({
            status: 409,
            error: { detail: { code: 'something_else' } },
          }),
      ),
    );
    await component.save();
    expect(component.error()).toBe('manual_faces.save_failed');
  });
  it('retains the same create identity after failure, and commits actual response', async () => {
    api.post.mockReturnValueOnce(throwError(() => new Error('lost response')));
    await component.save();
    await component.save();
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]);
    expect(component.regions()).toEqual([region]);
    expect(committed).toHaveBeenCalledTimes(1);
  });
  it('refreshes the canonical frame while preserving the draft and retry identity', async () => {
    api.post.mockReturnValue(throwError(() => new Error('response lost')));
    await component.save();
    api.get.mockImplementation((path: string) =>
      of(
        path.endsWith('frame')
          ? { image_base64: 'newjpeg', width: 100, height: 200, frame_token: 'fresh' }
          : { regions: [] },
      ),
    );
    await component.reloadFrame();
    expect(component.bbox()).toEqual([0.1, 0.2, 0.8, 0.9]);
    expect(component.person()).toEqual({ person_id: 5 });
    component.setCoordinate(0, 10);
    await component.save();
    expect(api.post.mock.calls[0][1].client_id).toBe(api.post.mock.calls[1][1].client_id);
    expect(api.post.mock.calls[1][1].frame_token).toBe('fresh');
  });
  it('distinguishes a saved mark from a failed membership refresh', async () => {
    committed.mockRejectedValue(new Error('refresh offline'));
    await component.save();
    expect(component.regions()).toEqual([region]);
    expect(component.error()).toBe('manual_faces.refresh_failed');
    expect(component.person()).toBeNull();
  });
  it('changes retry identity when the draft changes', async () => {
    api.post.mockReturnValue(throwError(() => new Error('offline')));
    await component.save();
    component.bbox.set([0.2, 0.2, 0.8, 0.9]);
    await component.save();
    expect(api.post.mock.calls[0][1].client_id).not.toBe(api.post.mock.calls[1][1].client_id);
  });
  it('loads saved marks even when the original cannot be decoded', async () => {
    api.get.mockImplementation((path: string) =>
      path.endsWith('frame')
        ? throwError(() => new Error('missing'))
        : of({ regions: [{ ...region, source_changed: true }] }),
    );
    await component.load();
    expect(component.regions()[0].source_changed).toBe(true);
    expect(component.frameUnavailable()).toBe(true);
  });
  it('uses actual image content bounds for pointer coordinates', () => {
    const target = {
      getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 400 }),
      setPointerCapture: vi.fn(),
    };
    const event = (x: number, y: number) =>
      ({
        currentTarget: target,
        clientX: x,
        clientY: y,
        pointerId: 1,
        button: 0,
        preventDefault: vi.fn(),
      }) as unknown as PointerEvent;
    component.startDraw(event(260, 410));
    component.endDraw(event(80, 90));
    expect(component.bbox()).toEqual([0, 0.1, 0.8, 0.9]);
  });
  it('requires deliberate coordinates for a stale region and supports keyboard numeric editing', async () => {
    component.edit({ ...region, source_changed: true });
    await component.save();
    expect(api.put).not.toHaveBeenCalled();
    component.setCoordinate(0, 20);
    await component.save();
    expect(api.put).toHaveBeenCalledWith(
      '/photo/manual-faces/3',
      expect.objectContaining({ bbox: [0.2, 0.2, 0.8, 0.9] }),
    );
  });
  it('defers removal until reload finishes so a delayed list cannot resurrect a deletion', async () => {
    component.regions.set([region]);
    const list = new Subject<{ regions: ManualFaceRegion[] }>();
    api.get.mockImplementation((path: string) =>
      path.endsWith('frame')
        ? of({ image_base64: 'fresh', width: 100, height: 200, frame_token: 'fresh' })
        : list,
    );
    const reload = component.reloadFrame();
    await component.remove(region);
    expect(api.delete).not.toHaveBeenCalled();
    list.next({ regions: [region] });
    list.complete();
    await reload;
    await component.remove(region);
    expect(api.delete).toHaveBeenCalledOnce();
    expect(component.regions()).toEqual([]);
  });
  it('deletes only the selected manual mark without needing a frame', async () => {
    component.frame.set(null);
    component.regions.set([region]);
    await component.remove(region);
    expect(api.delete).toHaveBeenCalledWith('/photo/manual-faces/3?path=%2Fa.raw');
    expect(component.regions()).toEqual([]);
    expect(committed).toHaveBeenCalledOnce();
  });
  it('does not write before Save and retains a failed draft', async () => {
    component.edit(region);
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
    api.put.mockReturnValue(throwError(() => new Error('offline')));
    await component.save();
    expect(component.bbox()).toEqual(region.bbox);
    expect(component.person()).toEqual({ person_id: 5 });
    expect(committed).not.toHaveBeenCalled();
  });
  it('rejects an overlong proposed person name without creating anything', async () => {
    component.person.set({ new_person_name: 'a'.repeat(121) });
    await component.save();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('accepts exactly four canonical pixels despite fraction rounding', async () => {
    component.bbox.set([0.26, 0.26, 0.3, 0.3]);
    await component.save();
    expect(api.post).toHaveBeenCalledOnce();
  });
  it('refuses rectangles smaller than four canonical pixels', async () => {
    component.bbox.set([0.1, 0.1, 0.11, 0.9]);
    await component.save();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('keeps captured request values and commits after destruction', async () => {
    const response = new Subject<ManualFaceRegion>();
    api.post.mockReturnValue(response);
    const pending = component.save();
    component.bbox.set([0, 0, 1, 1]);
    TestBed.resetTestingModule();
    response.next(region);
    response.complete();
    await pending;
    expect(api.post.mock.calls[0][1].bbox).toEqual([0.1, 0.2, 0.8, 0.9]);
    expect(committed).toHaveBeenCalledTimes(1);
  });
  describe('marking an object', () => {
    const object = { id: 9, label: 'birthday cake', box: [0.1, 0.2, 0.8, 0.9] };

    beforeEach(() => {
      component.kind.set('object');
      api.post.mockReturnValue(of(object));
    });

    it('saves a labelled box to the objects route and never touches faces', async () => {
      const changed = vi.fn();
      (component.data as { onObjectsChanged?: () => void }).onObjectsChanged = changed;
      component.objectLabel.set('  Birthday cake ');

      await component.saveObject();

      expect(api.post).toHaveBeenCalledTimes(1);
      expect(api.post).toHaveBeenCalledWith('/photo/objects', {
        path: '/a.raw', label: 'Birthday cake', box: [0.1, 0.2, 0.8, 0.9],
      });
      expect(component.objects()).toEqual([object]);
      expect(component.objectLabel()).toBe('');
      expect(changed).toHaveBeenCalledTimes(1);
      expect(committed).not.toHaveBeenCalled();
      expect(component.regions()).toEqual([]);
    });

    it('needs a label and a box', async () => {
      component.objectLabel.set('   ');
      expect(component.objectValid()).toBe(false);
      component.objectLabel.set('car');
      expect(component.objectValid()).toBe(true);
      component.bbox.set([0, 0, 0, 0]);
      expect(component.objectValid()).toBe(false);
      await component.saveObject();
      expect(api.post).not.toHaveBeenCalled();
    });

    it('removes an object through the objects route', async () => {
      component.objects.set([object]);
      await component.removeObject(object);
      expect(api.delete).toHaveBeenCalledWith('/photo/objects/9');
      expect(component.objects()).toEqual([]);
      expect(committed).not.toHaveBeenCalled();
    });
  });
});
