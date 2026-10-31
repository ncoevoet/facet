import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { Observable, Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import {
  FindMoreFacesDialogComponent,
  FIND_MORE_FETCH,
  FIND_MORE_PAGE,
  FIND_MORE_STRICTNESS,
  FaceOwner,
  PossibleFace,
  PossibleFacesResponse,
  SimilarGroup,
} from './find-more-faces-dialog.component';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';

const face = (face_id: number, similarity: number, owner: FaceOwner = 'ungrouped', person_name: string | null = null): PossibleFace => ({
  face_id,
  photo_path: `/p/${face_id}.jpg`,
  person_id: owner === 'ungrouped' ? null : 900 + face_id,
  person_name,
  similarity,
  distance: 1 - similarity,
  owner,
});

function answer(faces: PossibleFace[], extra: Partial<PossibleFacesResponse> = {}): PossibleFacesResponse {
  return {
    faces,
    candidates: 100,
    faces_scanned: 100,
    counts: { ungrouped: 4, unnamed_group: 2, named: 3 },
    best_similarity: faces.length ? faces[0].similarity : 0.23,
    similar_groups: [],
    ...extra,
  };
}

const overCeiling = () => throwError(() => new HttpErrorResponse({ status: 412, error: {
  detail: '300000 faces would be scanned, over the ceiling of 192000; narrow the scan with scope, path_prefix, date_from or date_to',
} }));

describe('FindMoreFacesDialogComponent', () => {
  let fixture: ComponentFixture<FindMoreFacesDialogComponent>;
  let component: FindMoreFacesDialogComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockDialog: { open: Mock };
  let dialogRef: { close: Mock; disableClose: boolean; backdropClick: Mock; keydownEvents: Mock };
  let backdrop: Subject<MouseEvent>;
  let keys: Subject<KeyboardEvent>;
  /** The answer each possible_faces call gets; the years endpoint answers on its own. */
  let search: Mock<(params: Record<string, unknown>) => Observable<PossibleFacesResponse>>;

  async function render(): Promise<void> {
    fixture = TestBed.createComponent(FindMoreFacesDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    await vi.waitFor(() => expect(component.loading()).toBe(false));
    fixture.detectChanges();
  }

  async function settle(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    await vi.waitFor(() => expect(component.loading()).toBe(false));
    fixture.detectChanges();
  }

  const q = <T extends Element = HTMLElement>(sel: string) => fixture.nativeElement.querySelector(sel) as T | null;
  const text = () => (fixture.nativeElement as HTMLElement).textContent!.replace(/\s+/g, ' ');
  const searches = () => mockApi.get.mock.calls.filter((c) => String(c[0]).includes('possible_faces')).map((c) => c[1]);

  beforeEach(() => {
    search = vi.fn(() => of(answer([face(1, 0.8), face(2, 0.45), face(3, 0.7, 'named', 'Bob')])));
    mockApi = {
      get: vi.fn((url: string, params: Record<string, unknown>) =>
        url === '/timeline/years' ? of({ years: [{ year: '2021' }, { year: '2023' }] }) : search(params)),
      post: vi.fn(() => of({ success: true })),
    };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };
    backdrop = new Subject<MouseEvent>();
    keys = new Subject<KeyboardEvent>();
    dialogRef = { close: vi.fn(), disableClose: false, backdropClick: vi.fn(() => backdrop), keydownEvents: vi.fn(() => keys) };
    TestBed.configureTestingModule({
      imports: [FindMoreFacesDialogComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key), translations: () => ({}) } },
        { provide: MAT_DIALOG_DATA, useValue: { personId: 7, personName: 'Anna' } },
        { provide: MatDialogRef, useValue: dialogRef },
      ],
    });
    // The dialog's own MatDialogModule import would shadow a plain provider.
    TestBed.overrideProvider(MatDialog, { useValue: mockDialog });
  });

  describe('owner chips', () => {
    it('searches every face, ungrouped and unnamed groups by default, at Normal', async () => {
      await render();
      expect(searches()[0]).toEqual({
        scope: 'all', owners: 'ungrouped,unnamed_group,named', per_owner: 'true', limit: FIND_MORE_FETCH, min_similarity: FIND_MORE_STRICTNESS.normal,
      });
      expect(FIND_MORE_STRICTNESS).toEqual({ very_strict: 0.6, strict: 0.5, normal: 0.35, loose: 0.25, very_loose: 0.2 });
      const chips = [...fixture.nativeElement.querySelectorAll('[data-owner]')] as HTMLElement[];
      expect(chips.map((c) => [c.dataset['owner'], c.getAttribute('aria-pressed')])).toEqual([
        ['ungrouped', 'true'], ['unnamed_group', 'true'], ['named', 'false'],
      ]);
      expect(chips[0].textContent).toContain('persons.find_more_owner_ungrouped');
      expect(component.chips().map((c) => c.count)).toEqual([4, 2, 3]);
    });

    it('toggling a chip filters the fetched faces without a new search, and the match count follows', async () => {
      await render();
      expect(component.matchCount()).toBe(6);
      expect(component.faces().map((f) => f.face_id)).toEqual([1, 2]);
      q<HTMLButtonElement>('[data-owner="named"]')!.click();
      await settle();
      expect(searches().length).toBe(1);
      expect(component.faces().map((f) => f.face_id)).toEqual([1, 2, 3]);
      expect(component.matchCount()).toBe(9);
      expect(q('[data-match-count]')!.textContent).toContain('persons.find_more_matches');
      q<HTMLButtonElement>('[data-owner="ungrouped"]')!.click();
      await settle();
      expect(searches().length).toBe(1);
      expect(component.faces().map((f) => f.face_id)).toEqual([3]);
    });

    it('changing the strictness still searches again', async () => {
      await render();
      component.setStrictness('loose');
      await settle();
      expect(searches().length).toBe(2);
      expect(searches()[1]).toMatchObject({ min_similarity: FIND_MORE_STRICTNESS.loose, per_owner: 'true' });
    });

    it('in the narrowed search a chip toggle searches again, as before', async () => {
      search.mockReturnValueOnce(overCeiling());
      await render();
      expect(component.fallback()).toBe('ungrouped');
      const before = searches().length;
      component.toggleOwner('named');
      await settle();
      expect(searches().length).toBe(before + 1);
      expect(searches().at(-1)).toMatchObject({ scope: 'unassigned', owners: 'ungrouped' });
    });

    it('the last chip on cannot be turned off', async () => {
      await render();
      component.toggleOwner('unnamed_group');
      await settle();
      expect(q<HTMLButtonElement>('[data-owner="ungrouped"]')!.disabled).toBe(true);
      component.toggleOwner('ungrouped');
      expect(component.owners().has('ungrouped')).toBe(true);
    });

    it('a named face says whose it is, starts unticked, and ticking it warns that it moves', async () => {
      await render();
      component.toggleOwner('named');
      await settle();
      expect(text()).toContain('persons.find_more_from');
      expect(component.selectedIds().has(3)).toBe(false);
      expect(q('[data-moves-warning]')).toBeNull();
      component.toggle(3);
      fixture.detectChanges();
      expect(q('[data-moves-warning]')!.textContent).toContain('persons.find_more_moves_warning');
    });
  });

  describe('confidence', () => {
    it('badges strong (50%+) and possible matches, with the percentage', async () => {
      await render();
      component.toggleOwner('named');
      await settle();
      const rows = component.rows();
      expect(rows.map((r) => [r.face_id, r.strong, r.percent])).toEqual([[1, true, 80], [2, false, 45], [3, true, 70]]);
      const badges = ([...fixture.nativeElement.querySelectorAll('[data-face]')] as HTMLElement[]).map((b) => b.textContent!);
      expect(badges[0]).toContain('persons.find_more_strong');
      expect(badges[1]).toContain('persons.find_more_possible');
    });

    it('Strict and Loose search again at 0.50 and 0.25', async () => {
      await render();
      component.setStrictness('strict');
      await settle();
      component.setStrictness('loose');
      await settle();
      expect(searches().map((p) => p?.['min_similarity'])).toEqual([0.35, 0.5, 0.25]);
    });

    it('pre-ticks strong matches no other named person owns', async () => {
      search.mockReturnValue(of(answer([face(5, 0.9, 'named', 'Anna'), face(6, 0.9, 'named', 'Bob'), face(8, 0.9, 'unnamed_group')])));
      await render();
      component.toggleOwner('named');
      await settle();
      expect([...component.selectedIds()].sort()).toEqual([5, 8]);
    });
  });

  describe('similar groups', () => {
    const GROUPS: SimilarGroup[] = [
      { person_id: 40, name: null, face_count: 12, similarity: 0.71 },
      { person_id: 41, name: 'Carla', face_count: 30, similarity: 0.66 },
    ];

    it('lists the unnamed groups, and the named ones only with the Named chip', async () => {
      search.mockReturnValue(of(answer([face(1, 0.8)], { similar_groups: GROUPS })));
      await render();
      expect(component.groups().map((g) => g.person_id)).toEqual([40]);
      const row = q('[data-group="40"]')!;
      expect(row.querySelector('img')!.getAttribute('src')).toContain('40');
      expect(row.textContent).toContain('persons.find_more_unnamed_group');
      expect(row.textContent).toContain('persons.find_more_alike');
      component.toggleOwner('named');
      await settle();
      expect(component.groups().map((g) => g.person_id)).toEqual([40, 41]);
    });

    it('Merge all folds an unnamed group in without asking, drops the row and refreshes the faces', async () => {
      search.mockReturnValue(of(answer([face(1, 0.8)], { similar_groups: GROUPS })));
      await render();
      const clear = vi.spyOn(TestBed.inject(PersonFaceBoxesService), 'clear');
      search.mockReturnValue(of(answer([face(9, 0.6)], { similar_groups: GROUPS.slice(1) })));
      (q('[data-group="40"] button') as HTMLButtonElement).click();
      await settle();
      expect(mockDialog.open).not.toHaveBeenCalled();
      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge', { source_id: 40, target_id: 7 });
      expect(clear).toHaveBeenCalled();
      expect(q('[data-group="40"]')).toBeNull();
      expect(component.faces().map((f) => f.face_id)).toEqual([9]);
      component.close();
      expect(dialogRef.close).toHaveBeenCalledWith({ added: 12 });
    });

    it('a named group is confirmed first, and a declined confirm merges nothing', async () => {
      search.mockReturnValue(of(answer([face(1, 0.8)], { similar_groups: GROUPS })));
      await render();
      mockDialog.open.mockReturnValue({ afterClosed: () => of(false) });
      await component.mergeGroup(GROUPS[1]);
      expect(mockDialog.open).toHaveBeenCalledWith(ConfirmDialogComponent, expect.anything());
      expect(mockApi.post).not.toHaveBeenCalled();
      mockDialog.open.mockReturnValue({ afterClosed: () => of(true) });
      await component.mergeGroup(GROUPS[1]);
      expect(mockApi.post).toHaveBeenCalledWith('/persons/merge', { source_id: 41, target_id: 7 });
    });
  });

  describe('empty state', () => {
    it('says how close the best face came, and offers Loose and named people', async () => {
      search.mockReturnValue(of(answer([], { best_similarity: 0.23, counts: { ungrouped: 0, unnamed_group: 0, named: 2 } })));
      await render();
      expect(q('[data-empty]')!.textContent).toContain('persons.find_more_none_closest');
      expect(component.closest()).toEqual({ percent: 23 });
      q<HTMLButtonElement>('[data-try-loose]')!.click();
      await settle();
      expect(searches().at(-1)).toMatchObject({ min_similarity: 0.25 });
      expect(q('[data-try-loose]')).toBeNull();
      q<HTMLButtonElement>('[data-include-named]')!.click();
      await settle();
      expect(component.owners().has('named')).toBe(true);
      expect(q('[data-include-named]')).toBeNull();
    });

    it('offers no named people when none match', async () => {
      search.mockReturnValue(of(answer([], { counts: { ungrouped: 0, unnamed_group: 0, named: 0 } })));
      await render();
      expect(q('[data-include-named]')).toBeNull();
    });
  });

  describe('too many faces (412)', () => {
    it('retries on the ungrouped faces alone and says why', async () => {
      search.mockReturnValueOnce(overCeiling());
      await render();
      expect(searches()[1]).toEqual({
        scope: 'unassigned', owners: 'ungrouped', limit: FIND_MORE_FETCH, min_similarity: FIND_MORE_STRICTNESS.normal,
      });
      expect(component.fallback()).toBe('ungrouped');
      expect(q('[data-fallback]')!.textContent).toContain('persons.find_more_fallback_ungrouped');
      expect(component.faces().length).toBe(3);
      expect(text()).not.toContain('ceiling');
    });

    it('then asks for a year, and searches that year', async () => {
      search.mockReturnValueOnce(overCeiling()).mockReturnValueOnce(overCeiling());
      await render();
      expect(component.fallback()).toBe('year');
      expect(searches().length).toBe(2);
      expect(q('[data-fallback]')!.textContent).toContain('persons.find_more_fallback_year');
      await vi.waitFor(() => expect(component.years()).toEqual(['2023', '2021']));
      component.pickYear('2021');
      await settle();
      expect(searches()[2]).toMatchObject({ scope: 'unassigned', owners: 'ungrouped', date_from: '2021-01-01', date_to: '2021-12-31' });
      expect(component.faces().length).toBe(3);
    });

    it('a year still over the ceiling says so in words, never the server detail', async () => {
      search.mockReturnValueOnce(overCeiling()).mockReturnValueOnce(overCeiling()).mockReturnValueOnce(overCeiling());
      await render();
      component.pickYear('2021');
      await settle();
      expect(component.error()).toBe('persons.find_more_too_many_unassigned');
      expect(text()).not.toContain('ceiling');
    });

    it('explains a missing centroid instead of retrying', async () => {
      search.mockReturnValue(throwError(() => new HttpErrorResponse({
        status: 412, error: { detail: 'This person has no centroid yet; run face clustering first' },
      })));
      await render();
      expect(component.error()).toBe('persons.find_more_no_centroid');
      expect(searches().length).toBe(1);
    });
  });

  describe('selection', () => {
    it('Select all strong ticks the 50%+ faces only', async () => {
      await render();
      component.toggleOwner('named');
      await settle();
      component.clearSelection();
      component.selectStrong();
      expect([...component.selectedIds()].sort()).toEqual([1, 3]);
    });

    it('shift-click ticks the range from the last face clicked', async () => {
      search.mockReturnValue(of(answer([face(1, 0.4), face(2, 0.4), face(3, 0.4), face(4, 0.4)])));
      await render();
      const faces = () => [...fixture.nativeElement.querySelectorAll('[data-face]')] as HTMLElement[];
      faces()[0].click();
      fixture.detectChanges();
      faces()[3].dispatchEvent(new MouseEvent('click', { shiftKey: true, bubbles: true }));
      fixture.detectChanges();
      expect([...component.selectedIds()].sort()).toEqual([1, 2, 3, 4]);
    });

    it('Space toggles the focused face', async () => {
      await render();
      const second = fixture.nativeElement.querySelector('[data-face="2"]') as HTMLElement;
      second.focus();
      const ev = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
      second.dispatchEvent(ev);
      fixture.detectChanges();
      expect(component.selectedIds().has(2)).toBe(true);
      expect(ev.defaultPrevented).toBe(true);
    });

    it('the Add button carries the selection count', async () => {
      await render();
      expect(q('[data-add]')!.textContent).toContain('persons.find_more_add');
      expect(component.selectedIds().size).toBe(1);
    });
  });

  describe('rounds', () => {
    it('shows at most one page of faces', async () => {
      search.mockReturnValue(of(answer(Array.from({ length: FIND_MORE_PAGE + 10 }, (_, i) => face(i + 1, 0.4)))));
      await render();
      expect(component.faces().length).toBe(FIND_MORE_PAGE);
    });

    it('an add shows the next fetched page instead of scanning again, and the counts drop', async () => {
      search.mockReturnValue(of(answer(Array.from({ length: FIND_MORE_PAGE + 5 }, (_, i) => face(i + 1, 0.4)))));
      await render();
      component.toggle(1);
      await component.addSelected();
      expect(mockApi.post).toHaveBeenCalledWith('/persons/7/assign_faces', { face_ids: [1] });
      expect(searches().length).toBe(1);
      expect(component.faces().map((f) => f.face_id)).toEqual([49, 50, 51, 52, 53]);
      expect(component.counts()!.ungrouped).toBe(3);
    });

    it('scans again once the fetched results run out, without the faces left unticked', async () => {
      await render();
      component.toggle(2);
      search.mockReturnValue(of(answer([face(3, 0.7, 'named', 'Bob'), face(4, 0.6)])));
      const clear = vi.spyOn(TestBed.inject(PersonFaceBoxesService), 'clear');
      await component.addSelected();
      expect(mockApi.post).toHaveBeenCalledWith('/persons/7/assign_faces', { face_ids: [1, 2] });
      expect(clear).toHaveBeenCalled();
      expect(searches().length).toBe(2);
      // Face 3 was shown and left unticked, so the next round drops it.
      expect(component.faces().map((f) => f.face_id)).toEqual([4]);
      component.close();
      expect(dialogRef.close).toHaveBeenCalledWith({ added: 2 });
    });

    it('reports a failed add and keeps the dialog open', async () => {
      await render();
      mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
      await component.addSelected();
      expect(component.error()).toBe('persons.find_more_add_error');
      expect(component.busy()).toBe(false);
      expect(dialogRef.close).not.toHaveBeenCalled();
    });

    it('clears a failed add\'s error when the next add succeeds', async () => {
      search.mockReturnValue(of(answer(Array.from({ length: FIND_MORE_PAGE + 5 }, (_, i) => face(i + 1, 0.4)))));
      await render();
      component.toggle(1);
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));
      await component.addSelected();
      expect(component.error()).toBe('persons.find_more_add_error');
      await component.addSelected();
      expect(component.error()).toBeNull();
      fixture.detectChanges();
      expect(q('[data-face]')).not.toBeNull();
    });

    it('clears a failed merge\'s error when the next merge succeeds', async () => {
      await render();
      const group = { person_id: 55, name: null, face_count: 3, similarity: 0.6 } as SimilarGroup;
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));
      await component.mergeGroup(group);
      expect(component.error()).toBe('persons.find_more_merge_error');
      await component.mergeGroup(group);
      expect(component.error()).toBeNull();
    });
  });

  describe('closing', () => {
    it('blocks the default close so every path goes through close()', async () => {
      await render();
      expect(dialogRef.disableClose).toBe(true);
    });

    it('Escape after an add closes with the count added', async () => {
      await render();
      await component.addSelected();
      keys.next(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(dialogRef.close).toHaveBeenCalledWith({ added: 1 });
    });

    it('a backdrop click after an add closes with the count added', async () => {
      await render();
      await component.addSelected();
      backdrop.next(new MouseEvent('click'));
      expect(dialogRef.close).toHaveBeenCalledWith({ added: 1 });
    });

    it('other keys do not close', async () => {
      await render();
      keys.next(new KeyboardEvent('keydown', { key: 'a' }));
      expect(dialogRef.close).not.toHaveBeenCalled();
    });
  });

  describe('Try Loose', () => {
    it.each(['loose', 'very_loose'] as const)('is not offered at %s', async (level) => {
      search.mockReturnValue(of(answer([])));
      await render();
      component.setStrictness(level);
      await settle();
      expect(q('[data-try-loose]')).toBeNull();
    });

    it.each(['very_strict', 'strict', 'normal'] as const)('is offered at %s', async (level) => {
      search.mockReturnValue(of(answer([])));
      await render();
      component.setStrictness(level);
      await settle();
      expect(q('[data-try-loose]')).not.toBeNull();
    });
  });

  describe('face tile name', () => {
    it('carries the match detail and the owner it comes from', async () => {
      await render();
      component.toggleOwner('named');
      await settle();
      expect(q('[data-face="1"]')!.getAttribute('aria-label')).toContain('persons.find_more_select_face_detail');
      expect(q('[data-face="1"]')!.getAttribute('aria-label')).not.toContain('persons.find_more_from');
      expect(q('[data-face="3"]')!.getAttribute('aria-label')).toContain('persons.find_more_from');
    });
  });
});
