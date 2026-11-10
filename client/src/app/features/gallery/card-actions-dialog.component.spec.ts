import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { DEFAULT_CARD_ACTIONS } from '../../shared/components/photo-card/card-actions';
import { CardActionsDialogComponent } from './card-actions-dialog.component';
import { CardActionsService } from './card-actions.service';

describe('CardActionsDialogComponent', () => {
  let close: ReturnType<typeof vi.fn>;

  function build(saved?: object, edition = true) {
    localStorage.removeItem('facet_card_actions');
    if (saved) localStorage.setItem('facet_card_actions', JSON.stringify(saved));
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [CardActionsDialogComponent],
      providers: [
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
        { provide: MatDialogRef, useValue: { close } },
        { provide: AuthService, useValue: { isEdition: signal(edition) } },
      ],
    });
    const fixture = TestBed.createComponent(CardActionsDialogComponent);
    fixture.detectChanges();
    return { fixture, service: TestBed.inject(CardActionsService) };
  }

  const rows = (el: HTMLElement) => [...el.querySelectorAll('mat-dialog-content mat-checkbox')];
  const actionButton = (el: HTMLElement, label: string) =>
    [...el.querySelectorAll<HTMLButtonElement>('mat-dialog-actions button')].find(b => b.textContent?.includes(label))!;

  it('hides edition-only actions without edition rights and keeps their slot when moving around them', () => {
    const { fixture, service } = build(undefined, false);
    const el = fixture.nativeElement as HTMLElement;
    const labels = rows(el).map(r => r.textContent!);
    expect(labels.some(t => t.includes('photoCard.embed_to_file') || t.includes('manage_persons.assign_face'))).toBe(false);
    expect(labels.some(t => t.includes('critique.title'))).toBe(true);
    expect(rows(el)).toHaveLength(DEFAULT_CARD_ACTIONS.order.length - 2);
    // critique (visible #1) moves down past the hidden embed/assign_face to swap with duplicate_set.
    el.querySelectorAll<HTMLButtonElement>('button[aria-label="gallery.card_actions.move_down"]')[1].click();
    actionButton(el, 'ui.buttons.save').click();
    expect(service.config().order).toEqual(['similar', 'duplicate_set', 'embed', 'assign_face', 'critique', 'burst_set', 'sequence_set', 'stack_set', 'open_detail']);
  });

  it('moves a row down, shows a hidden one, and saves both to the service', () => {
    const { fixture, service } = build();
    const el: HTMLElement = fixture.nativeElement;
    const firstRowDown = el.querySelectorAll<HTMLButtonElement>('button[aria-label="gallery.card_actions.move_down"]')[0];
    firstRowDown.click();
    // `open_detail` ships hidden: ticking its box shows it.
    const openDetail = rows(el).find(r => r.textContent?.includes('photoCard.open_detail'))!;
    openDetail.querySelector('input')!.click();
    fixture.detectChanges();

    actionButton(el, 'ui.buttons.save').click();

    const [first, second, ...rest] = DEFAULT_CARD_ACTIONS.order;
    expect(service.config().order).toEqual([second, first, ...rest]);
    expect(service.config().hidden).not.toContain('open_detail');
    expect(close).toHaveBeenCalled();
  });

  it('disables moving the first row up and the last row down', () => {
    const { fixture } = build();
    const el: HTMLElement = fixture.nativeElement;
    const ups = el.querySelectorAll<HTMLButtonElement>('button[aria-label="gallery.card_actions.move_up"]');
    const downs = el.querySelectorAll<HTMLButtonElement>('button[aria-label="gallery.card_actions.move_down"]');
    expect(ups[0].disabled).toBe(true);
    expect(downs[downs.length - 1].disabled).toBe(true);
  });

  it('reset restores the default layout without saving until Save', () => {
    const reversed = [...DEFAULT_CARD_ACTIONS.order].reverse();
    const { fixture, service } = build({ order: reversed, hidden: [] });
    const el: HTMLElement = fixture.nativeElement;

    actionButton(el, 'gallery.card_actions.reset').click();
    expect(service.config().order).toEqual(reversed);

    actionButton(el, 'ui.buttons.save').click();
    expect(service.config()).toEqual(DEFAULT_CARD_ACTIONS);
  });
});
