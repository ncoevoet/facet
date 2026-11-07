import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { PersonAssignmentHistoryService } from '../../core/services/person-assignment-history.service';
import { AuthService } from '../../core/services/auth.service';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';
import { I18nService } from '../../core/services/i18n.service';
import { ApiService } from '../../core/services/api.service';
import type { PersonOption } from './gallery.store';

const alice: PersonOption = { id: 1, name: 'Alice', face_count: 1 };
const bob: PersonOption = { id: 2, name: 'Bob', face_count: 3 };
describe('PersonSelectorDialogComponent existing-person-only review', () => {
  it('does not offer or return Create when the caller requires an existing target', async () => {
    const close = vi.fn();
    TestBed.configureTestingModule({ imports: [PersonSelectorDialogComponent], providers: [
      { provide: AuthService, useValue: { identity: () => 'owner' } },
      { provide: PersonAssignmentHistoryService, useValue: { recentIds: () => [] } },
      { provide: ApiService, useValue: { get: () => of({ persons: [alice], total: 1 }) } },
      { provide: MatDialogRef, useValue: { close } }, { provide: MAT_DIALOG_DATA, useValue: { allowCreate: false } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(PersonSelectorDialogComponent);
    fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('person_selector.create_new');
    fixture.componentInstance.startCreate(); fixture.componentInstance.newName = 'New person'; fixture.componentInstance.confirmCreate();
    expect(close).not.toHaveBeenCalled();
    expect(fixture.componentInstance.creating()).toBe(false);
  });
});
describe('PersonSelectorDialogComponent server search', () => {
  const identity = signal('1|test');
  const recentIds = vi.fn(() => [] as number[]);
  let component: PersonSelectorDialogComponent;
  let get: ReturnType<typeof vi.fn>;
  let close: ReturnType<typeof vi.fn>;
  beforeEach(async () => {
    vi.useFakeTimers();
    identity.set('1|test');
    recentIds.mockReturnValue([]);
    get = vi.fn(() => of({ persons: [alice], total: 1 }));
    close = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { identity } },
        PersonSelectorDialogComponent,
        { provide: PersonAssignmentHistoryService, useValue: { recentIds } },
        { provide: ApiService, useValue: { get } },
        { provide: MatDialogRef, useValue: { close } },
      ],
    });
    component = TestBed.inject(PersonSelectorDialogComponent);
    await Promise.resolve();
  });
  afterEach(() => vi.useRealTimers());
  it('includes visible people with only one appearance via bounded server pagination', () => {
    expect(get).toHaveBeenCalledWith('/persons', {
      page: 1,
      per_page: 48,
      search: '',
      sort: 'assignment',
      recent_ids: '',
    });
    expect(component.filtered()).toEqual([alice]);
  });
  it('debounces server search instead of filtering a gallery dropdown', async () => {
    get.mockReturnValue(of({ persons: [bob], total: 1 }));
    component.searchQuery = 'Bo';
    component.filter();
    component.searchQuery = 'Bob';
    component.filter();
    await vi.advanceTimersByTimeAsync(249);
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(get).toHaveBeenLastCalledWith('/persons', {
      page: 1,
      per_page: 48,
      search: 'Bob',
      sort: 'assignment',
      recent_ids: '',
    });
    expect(component.filtered()).toEqual([bob]);
  });
  it('discards late responses for a superseded search', async () => {
    const old = new Subject<{ persons: PersonOption[]; total: number }>();
    get.mockReturnValueOnce(old).mockReturnValueOnce(of({ persons: [bob], total: 1 }));
    component.searchQuery = 'Alice';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    component.searchQuery = 'Bob';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    old.next({ persons: [alice], total: 1 });
    old.complete();
    await Promise.resolve();
    expect(component.filtered()).toEqual([bob]);
  });
  it('loads additional pages without a minimum appearance cutoff', async () => {
    get.mockReturnValueOnce(
      of({ persons: [alice, { id: 9, name: null, face_count: 8 }], total: 49 }),
    );
    component.searchQuery = '';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    expect(component.hasMore()).toBe(true);
    expect(component.filtered()).toEqual([alice]);
    get.mockReturnValueOnce(of({ persons: [bob], total: 49 }));
    await component.loadMore();
    expect(get).toHaveBeenLastCalledWith('/persons', {
      page: 2,
      per_page: 48,
      search: '',
      sort: 'assignment',
      recent_ids: '',
    });
    expect(component.filtered()).toEqual([alice, bob]);
    expect(component.hasMore()).toBe(false);
  });
  it('shows failure and retries the failed page without discarding previous results', async () => {
    get.mockReturnValueOnce(of({ persons: [alice], total: 49 }));
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    get.mockReturnValueOnce(throwError(() => new Error('offline')));
    await component.loadMore();
    expect(component.failed()).toBe(true);
    expect(component.filtered()).toEqual([alice]);
    get.mockReturnValueOnce(of({ persons: [bob], total: 49 }));
    await component.retry();
    expect(component.filtered()).toEqual([alice, bob]);
    expect(component.failed()).toBe(false);
  });
  it('cancels pending debounce and ignores responses after destruction', async () => {
    const pending = new Subject<{ persons: PersonOption[]; total: number }>();
    get.mockReturnValueOnce(pending);
    component.searchQuery = 'late';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    component.searchQuery = 'never';
    component.filter();
    const count = get.mock.calls.length;
    TestBed.resetTestingModule();
    await vi.advanceTimersByTimeAsync(250);
    pending.next({ persons: [bob], total: 1 });
    pending.complete();
    await Promise.resolve();
    expect(get).toHaveBeenCalledTimes(count);
    expect(component.filtered()).toEqual([]);
  });
  it('keeps creation a proposal and cancellation makes no write', () => {
    component.searchQuery = ' Grace ';
    component.startCreate();
    component.confirmCreate();
    expect(close).toHaveBeenCalledWith({ kind: 'create', name: 'Grace' });
    component.startCreate();
    component.cancelCreate();
    expect(component.newName).toBe('');
    expect(get).toHaveBeenCalledTimes(1);
  });
  it('holds the recent snapshot while searching and paging without reshuffling loaded rows', async () => {
    recentIds.mockReturnValue([9]); // Another assignment after this dialog opened.
    get.mockReturnValueOnce(of({ persons: [bob, alice], total: 49 }));
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    get.mockReturnValueOnce(of({ persons: [bob, { id: 3, name: 'Cara', face_count: 1 }], total: 49 }));
    await component.loadMore();
    expect(get).toHaveBeenLastCalledWith('/persons', expect.objectContaining({ recent_ids: '' }));
    expect(component.filtered().map((row) => row.id)).toEqual([2, 1, 3]);
  });
  it('closes on an identity change and ignores old candidate responses', async () => {
    const response = new Subject<{ persons: PersonOption[]; total: number }>();
    get.mockReturnValueOnce(response);
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    identity.set('1|other');
    TestBed.tick();
    response.next({ persons: [bob], total: 1 });
    response.complete();
    await Promise.resolve();
    expect(close).toHaveBeenCalledWith(null);
    expect(component.filtered()).toEqual([]);
  });

});


describe('PersonSelectorDialogComponent rendered accessibility', () => {
  it('associates the ordering hint with search and renders singular face text', async () => {
    TestBed.configureTestingModule({ providers: [
      { provide: AuthService, useValue: { identity: () => '1|test' } },
      { provide: PersonAssignmentHistoryService, useValue: { recentIds: () => [] } },
      { provide: ApiService, useValue: { get: () => of({ persons: [alice, bob], total: 2 }) } },
      { provide: MatDialogRef, useValue: { close: vi.fn() } },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string, params?: Record<string, unknown>) =>
        key === 'person_selector.face_count_one' ? '1 face' : key === 'person_selector.face_count' ? `${params?.['count']} faces` : key } },
    ] });
    const fixture = TestBed.createComponent(PersonSelectorDialogComponent);
    await fixture.whenStable();
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input');
    const hint = fixture.nativeElement.querySelector('#person-assignment-ordering-hint');
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(hint.id);
    expect(fixture.nativeElement.textContent).toContain('1 face');
    expect(fixture.nativeElement.textContent).not.toContain('1 faces');
    expect(fixture.nativeElement.textContent).toContain('3 faces');
  });
});
