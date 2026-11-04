import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NavigationCancel, NavigationStart, Router } from '@angular/router';
import { of, Subject } from 'rxjs';
import type { Mock } from 'vitest';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PhotoAnalysisComponent } from './photo-analysis.component';

const evidence = { aggregate: 7, category_reason: { reason_key: 'default' }, breakdown: [], penalties: {}, vlm_available: true };

describe('PhotoAnalysisComponent ownership', () => {
  function render(edition = true, overlay = false) {
    const reads: Subject<unknown>[] = [];
    const generation = new Subject();
    const api: { get: Mock; post: Mock } = { get: vi.fn(() => { const result = new Subject(); reads.push(result); return result; }), post: vi.fn(() => generation) };
    const auth = { identity: signal('alice'), status: signal({ user_id: 'alice' }), token: 'alice-token', isEdition: signal(edition), hasFeature: () => overlay };
    const router = { url: '/photo', events: new Subject() };
    TestBed.configureTestingModule({ imports: [PhotoAnalysisComponent], providers: [
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
      { provide: Router, useValue: router }, { provide: MatSnackBar, useValue: { open: vi.fn() } },
      { provide: I18nService, useValue: { t: (key: string) => key, locale: () => 'en', translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(PhotoAnalysisComponent);
    fixture.componentRef.setInput('photoPath', '/first.jpg'); fixture.componentRef.setInput('vlmAvailable', true);
    fixture.detectChanges();
    return { fixture, api, auth, router, reads, generation, root: fixture.nativeElement as HTMLElement };
  }

  it('reads evidence without generating, then generates from the explicit rendered action', async () => {
    const { fixture, root, reads, api } = render();
    reads[0].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-analysis-generate]')!.click();
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/critique/vlm', { path: '/first.jpg', lang: 'en', refresh: false });
  });

  it('keeps the repeated thumbnail out of Analysis until overlay inspection is requested', async () => {
    const { fixture, root, reads } = render(true, true);
    reads[0].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('img')).toBeNull();
    const button = Array.from(root.querySelectorAll('button')).find(item => item.textContent?.includes('critique.overlay_show'))!;
    button.click(); fixture.detectChanges();
    expect(root.querySelectorAll('img')).toHaveLength(2);
    button.click(); fixture.detectChanges();
    expect(root.querySelector('img')).toBeNull();
  });

  it('keeps read-only evidence available without a generation action', async () => {
    const { fixture, root, reads, api } = render(false);
    reads[0].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('7.00');
    expect(root.querySelector('[data-analysis-generate]')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('recovers a failed evidence read through the rendered retry action', async () => {
    const { fixture, root, reads, api } = render();
    reads[0].error(new Error('offline')); await fixture.whenStable(); fixture.detectChanges();
    expect(root.querySelector('[data-analysis-retry]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-analysis-retry]')!.click(); fixture.detectChanges();
    expect(reads).toHaveLength(2); reads[1].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('7.00'); expect(root.querySelector('[data-analysis-retry]')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('preserves evidence after generation fails and refreshes stored commentary explicitly', async () => {
    const { fixture, root, reads, api, generation } = render();
    reads[0].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-analysis-generate]')!.click();
    generation.error(new Error('model unavailable')); await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('7.00'); expect(root.textContent).toContain('critique.error_fallback');
    api.post.mockReturnValueOnce(of({ ...evidence, vlm_critique: 'Stored commentary', vlm_source: 'cached' }));
    root.querySelector<HTMLButtonElement>('[data-analysis-generate]')!.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('Stored commentary');
    const refresh = root.querySelector<HTMLButtonElement>('[aria-label="critique.vlm_refresh"]')!;
    expect(refresh).toBeTruthy();
    api.post.mockReturnValueOnce(of({ ...evidence, vlm_critique: 'Fresh commentary', vlm_source: 'generated' }));
    refresh.click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.post).toHaveBeenLastCalledWith('/critique/vlm', { path: '/first.jpg', lang: 'en', refresh: true });
    expect(root.textContent).toContain('Fresh commentary'); expect(root.textContent).not.toContain('Stored commentary');
  });

  it('labels the score columns and keeps calculation background behind dismissible help', async () => {
    const { fixture, root, reads, api } = render();
    reads[0].next({ ...evidence, current_formula_score: 7,
      normalization_basis: 'persisted_percentiles',
      breakdown: [{ metric_key: 'aesthetic', value: 8, weight: 0.5, contribution: 4 }],
    });
    await fixture.whenStable(); fixture.detectChanges();
    expect(Array.from(root.querySelectorAll('thead th')).map(cell => cell.textContent?.trim())).toEqual([
      'critique.metric', 'critique.value', 'critique.weight', 'critique.contribution_label',
    ]);
    expect(root.querySelector('tbody th[scope="row"]')?.textContent).toContain('critique.metrics.aesthetic');
    expect(root.querySelector('tbody')?.textContent).toContain('50%');
    expect(root.querySelector('tbody')?.textContent).toContain('4.00');
    expect(root.textContent).not.toContain('critique.calculation_note');
    const help = root.querySelector<HTMLDetailsElement>('[data-context-help]')!;
    const trigger = help.querySelector<HTMLElement>('summary')!;
    trigger.click(); help.dispatchEvent(new Event('toggle'));
    fixture.detectChanges();
    expect(root.textContent).toContain('critique.calculation_note');
    expect(root.textContent).toContain('critique.normalization_basis.persisted_percentiles');
    help.querySelector<HTMLButtonElement>('[data-context-help-close]')!.click(); fixture.detectChanges();
    expect(help.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(root.textContent).not.toContain('critique.calculation_note');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('cancels old-photo reads and old-owner generation without adopting a different account', async () => {
    const { fixture, root, reads, api, auth, generation } = render();
    fixture.componentRef.setInput('photoPath', '/second.jpg'); fixture.detectChanges();
    expect(reads[0].observed).toBe(false);
    reads[0].next({ ...evidence, aggregate: 1 });
    reads[1].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    root.querySelector<HTMLButtonElement>('[data-analysis-generate]')!.click();
    expect(api.post).toHaveBeenCalledWith('/critique/vlm', { path: '/second.jpg', lang: 'en', refresh: false });
    auth.identity.set('bob'); auth.status.set({ user_id: 'bob' }); fixture.detectChanges();
    expect(generation.observed).toBe(false);
    generation.next({ ...evidence, vlm_critique: 'Alice private text' }); await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).not.toContain('Alice private text');
    expect(root.textContent).not.toContain('7.00');
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('rejects a captured write on token rotation, and reloads read-only evidence after cancelled navigation', async () => {
    const { fixture, root, reads, api, auth, router } = render();
    reads[0].next(evidence); await fixture.whenStable(); fixture.detectChanges();
    auth.token = 'rotated-token';
    root.querySelector<HTMLButtonElement>('[data-analysis-generate]')!.click();
    expect(api.post).not.toHaveBeenCalled();
    router.events.next(new NavigationStart(1, '/albums')); fixture.detectChanges();
    expect(root.textContent).not.toContain('7.00');
    api.get.mockReturnValueOnce(of({ ...evidence, aggregate: 8 }));
    router.events.next(new NavigationCancel(1, '/albums', 'guard refused')); fixture.detectChanges();
    await fixture.whenStable(); fixture.detectChanges();
    expect(root.textContent).toContain('8.00');
    expect(api.post).not.toHaveBeenCalled();
  });
});
