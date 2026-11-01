import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { of, Subject } from 'rxjs';
import type { Mock } from 'vitest';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PersonFaceBoxesService } from '../../shared/components/photo-card/person-face-boxes.service';
import { FaceReviewQueueComponent } from './face-review-queue.component';

@Component({ template: '' }) class OtherPage {}
const response = { faces: [
  { face_id: 1, photo_path: '/one.jpg', identity_token: 'a'.repeat(64), embedding_state: 'ready', suggestions: [{ person_id: 10, name: 'Alice', similarity: 0.9 }] },
  { face_id: 2, photo_path: '/two.jpg', identity_token: 'b'.repeat(64), embedding_state: 'ready', suggestions: [{ person_id: 20, name: 'Bob', similarity: 0.8 }] },
], total_unassigned: 2, next_after_id: null, model: 'arcface_buffalo_l', compared_people: 2, suggestions_requested: true };
const assigned = { assigned_count: 1, already: [], missing: [], skipped_model: [], skipped_hidden: [], skipped_assigned: [], skipped_changed: [] };

describe('FaceReviewQueueComponent', () => {
  async function render() {
    const api: { get: Mock; post: Mock } = { get: vi.fn(() => of(response)), post: vi.fn(() => of(assigned)) };
    const auth = { identity: signal('alice'), status: signal({ user_id: 'alice' }), isEdition: signal(true), token: 'token-a' };
    const boxes = { clear: vi.fn() };
    const chooserClosed = new Subject();
    const chooserRef = { close: vi.fn(() => { chooserClosed.next(null); chooserClosed.complete(); }), afterClosed: () => chooserClosed };
    const dialog: { open: Mock } = { open: vi.fn(() => chooserRef) };
    TestBed.configureTestingModule({ imports: [FaceReviewQueueComponent], providers: [
      provideRouter([{ path: 'persons', component: OtherPage }, { path: 'elsewhere', component: OtherPage }]),
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: MatDialog, useValue: dialog },
      { provide: PersonFaceBoxesService, useValue: boxes },
      { provide: I18nService, useValue: { t: (key: string, params?: object) => key + (params ? JSON.stringify(params) : ''), translations: () => ({}) } },
    ] });
    await TestBed.inject(Router).navigateByUrl('/persons?tab=matches');
    const fixture = TestBed.createComponent(FaceReviewQueueComponent);
    fixture.componentRef.setInput('mode', 'matches'); fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    document.body.appendChild(root);
    return { fixture, root, api, auth, boxes, dialog, chooserRef };
  }
  function select(root: HTMLElement) { root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(input => input.click()); }
  function preview(root: HTMLElement) { root.querySelector<HTMLButtonElement>('[data-review-selected]')!.click(); }

  it('shows the global queue and confirms captured face identities separately for each person', async () => {
    const { fixture, root, api, boxes } = await render();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    expect(root.querySelector('a')?.getAttribute('target')).toBe('_blank');
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-preview]')?.textContent).toContain('Alice');
    expect(api.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenNthCalledWith(1, '/persons/10/assign_faces', {
      face_ids: [1], only_unassigned: true, tolerant: true, expected_face_tokens: { '1': 'a'.repeat(64) }, expected_person_name: 'Alice',
    });
    expect(api.post).toHaveBeenNthCalledWith(2, '/persons/20/assign_faces', expect.objectContaining({ face_ids: [2], expected_person_name: 'Bob' }));
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":2,"skipped":0');
    expect(boxes.clear).toHaveBeenCalledTimes(2);
    fixture.destroy(); root.remove();
  });

  it('cancels a preview without writes and returns focus to its trigger', async () => {
    const { fixture, root, api } = await render();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector('[data-assignment-preview]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(root.querySelector('[data-assignment-preview]')).toBeNull();
    expect(document.activeElement).toBe(root.querySelector('[data-review-selected]'));
    expect(api.post).not.toHaveBeenCalled();
    fixture.destroy(); root.remove();
  });

  it('stops later person groups on token rotation and exposes recovery without a blind retry', async () => {
    const { fixture, root, api, auth } = await render();
    const pending = new Subject(); api.post.mockReturnValueOnce(pending);
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    auth.token = 'rotated'; pending.next(assigned); pending.complete();
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(root.textContent).toContain('persons.review_queue.uncertain');
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(0);
    expect(root.querySelector<HTMLButtonElement>('[data-queue-reload]')?.disabled).toBe(false);
    fixture.destroy(); root.remove();
  });

  it('retains completed counts when a later group fails and requires a read before another apply', async () => {
    const { fixture, root, api } = await render();
    const pending = new Subject(); api.post.mockReturnValueOnce(of(assigned)).mockReturnValueOnce(pending);
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await Promise.resolve(); pending.error(new Error('connection lost'));
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":1');
    expect(root.textContent).toContain('persons.review_queue.uncertain');
    expect(root.querySelector<HTMLButtonElement>('[data-review-selected]')?.disabled).toBe(true);
    expect(api.post).toHaveBeenCalledTimes(2);
    fixture.destroy(); root.remove();
  });

  it('resumes the owning queue after real same-page query navigation', async () => {
    const { fixture, root, api } = await render();
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/persons?tab=matches&view=recent');
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelectorAll('[data-review-face]')).toHaveLength(2);
    const reads = api.get.mock.calls.length;
    root.querySelector<HTMLButtonElement>('[data-queue-reload]')!.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(reads + 1);
    fixture.destroy(); root.remove();
  });

  it('closes the owned chooser when the queue is destroyed before an auth effect can run', async () => {
    const { fixture, root, dialog, chooserRef } = await render();
    const choosing = (fixture.componentInstance as any).chooseOther(response.faces[0], { currentTarget: root });
    const duplicate = (fixture.componentInstance as any).chooseOther(response.faces[0], { currentTarget: root });
    await duplicate;
    await vi.waitFor(() => expect(dialog.open).toHaveBeenCalled());
    expect(dialog.open).toHaveBeenCalledTimes(1);
    expect(dialog.open.mock.calls[0][1]).toEqual(expect.objectContaining({ data: { allowCreate: false } }));
    fixture.destroy(); await choosing;
    expect(chooserRef.close).toHaveBeenCalledWith(null);
    root.remove();
  });

  it('shows precise skipped-model receipts as a known refusal rather than unknown completion', async () => {
    const { fixture, root, api } = await render();
    api.post.mockReturnValueOnce(of({ ...assigned, assigned_count: 0, skipped_model: [1] }));
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!.click();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-assignment-receipt]')?.textContent).toContain('"assigned":1,"skipped":1');
    expect(root.querySelector('[data-receipt-reasons]')?.textContent).toContain('persons.review_queue.model_mismatch');
    expect(root.textContent).toContain('persons.review_queue.changed');
    expect(root.textContent).not.toContain('persons.review_queue.uncertain');
    fixture.destroy(); root.remove();
  });

  it('refuses captured confirmation after navigation starts', async () => {
    const { fixture, root, api } = await render();
    select(root); fixture.detectChanges(); preview(root); fixture.detectChanges();
    const confirm = root.querySelector<HTMLButtonElement>('[data-confirm-assignment]')!;
    await TestBed.inject(Router).navigateByUrl('/elsewhere');
    confirm.click(); fixture.detectChanges();
    expect(api.post).not.toHaveBeenCalled();
    expect(root.querySelector('[data-assignment-preview]')).toBeNull();
    fixture.destroy(); root.remove();
  });
});
