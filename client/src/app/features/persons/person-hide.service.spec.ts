import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { UndoService } from '../../core/services/undo.service';
import { IGNORE_UNDO_MS, PersonHideService } from './person-hide.service';

describe('PersonHideService', () => {
  let service: PersonHideService;
  let api: { post: ReturnType<typeof vi.fn> };
  let snackBar: { open: ReturnType<typeof vi.fn> };
  let journal: { record: ReturnType<typeof vi.fn> };
  let undo: { register: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    api = { post: vi.fn().mockReturnValue(of({})) };
    snackBar = { open: vi.fn() };
    journal = { record: vi.fn() };
    undo = { register: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: api },
        { provide: MatSnackBar, useValue: snackBar },
        { provide: I18nService, useValue: { t: (k: string) => k } },
        { provide: UserActivityJournal, useValue: journal },
        { provide: UndoService, useValue: undo },
      ],
    });
    service = TestBed.inject(PersonHideService);
  });

  it('Ignore posts hide, journals it and registers a 10 s Undo', async () => {
    expect(await service.setHidden(7, true, async () => undefined)).toBe(true);
    expect(api.post).toHaveBeenCalledWith('/persons/7/hide');
    expect(journal.record).toHaveBeenCalledWith('person', [], { action: 'hide', person_id: 7 });
    expect(undo.register).toHaveBeenCalledWith(expect.objectContaining({ labelKey: 'persons.hidden_done', durationMs: IGNORE_UNDO_MS }));
    expect(IGNORE_UNDO_MS).toBe(10_000);
  });

  it('Undo posts unhide, journals it, then runs the caller refresh', async () => {
    const onUndone = vi.fn().mockResolvedValue(undefined);
    await service.setHidden(7, true, onUndone);
    await undo.register.mock.calls[0][0].undo();
    expect(api.post).toHaveBeenLastCalledWith('/persons/7/unhide');
    expect(journal.record).toHaveBeenLastCalledWith('person', [], { action: 'unhide', person_id: 7 });
    expect(onUndone).toHaveBeenCalledTimes(1);
  });

  it('Restore posts unhide and says so, without an Undo', async () => {
    expect(await service.setHidden(7, false, async () => undefined)).toBe(true);
    expect(api.post).toHaveBeenCalledWith('/persons/7/unhide');
    expect(undo.register).not.toHaveBeenCalled();
    expect(snackBar.open).toHaveBeenCalledWith('persons.unhidden_done', '', { duration: 2000 });
  });

  it('a failed call shows the error, journals nothing and resolves false', async () => {
    api.post.mockReturnValue(throwError(() => new Error('boom')));
    expect(await service.setHidden(7, true, async () => undefined)).toBe(false);
    expect(snackBar.open).toHaveBeenCalledWith('persons.hide_error', '', { duration: 3000 });
    expect(journal.record).not.toHaveBeenCalled();
    expect(undo.register).not.toHaveBeenCalled();
  });
});
