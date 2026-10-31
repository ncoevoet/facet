import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { CARD_ACTION_META, CardActionId, CardActionsConfig, DEFAULT_CARD_ACTIONS } from '../../shared/components/photo-card/card-actions';
import { CardActionsService } from './card-actions.service';

/** Reorder and show/hide the photo card's hover buttons. Arrows rather than a
 *  drag list: the dialog has at most eight rows and keyboard-operable arrows
 *  need no drag-and-drop polyfill to stay accessible. */
@Component({
  selector: 'app-card-actions-dialog',
  standalone: true,
  imports: [MatButtonModule, MatCheckboxModule, MatIconModule, MatDialogModule, MatTooltipModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="!flex !items-center !gap-3 !m-0 !px-6 !pt-5 !pb-4 before:!content-none">
      <span class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
        <mat-icon aria-hidden="true" class="!text-xl !leading-none !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">tune</mat-icon>
      </span>
      <span class="flex flex-col">
        <span class="!text-base !font-semibold">{{ I18N.gallery.card_actions.title | translate }}</span>
        <span class="!text-xs !font-normal opacity-60 mt-0.5">{{ I18N.gallery.card_actions.hint | translate }}</span>
      </span>
    </h2>
    <mat-dialog-content class="!px-6 !pb-1">
      <div class="flex flex-col gap-1">
        @for (id of order(); track id; let i = $index) {
          <div class="flex items-center gap-2 px-2 py-1 rounded hover:bg-[var(--mat-sys-surface-container-high)]">
            <mat-checkbox [checked]="!hidden().has(id)" (change)="toggle(id, $event.checked)">
              <span class="flex items-center gap-2">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-70">{{ CARD_ACTION_META[id].icon }}</mat-icon>
                {{ CARD_ACTION_META[id].labelKey | translate }}
              </span>
            </mat-checkbox>
            <span class="ml-auto flex items-center">
              <button mat-icon-button class="!w-8 !h-8" [disabled]="i === 0"
                      [matTooltip]="I18N.gallery.card_actions.move_up | translate"
                      [attr.aria-label]="I18N.gallery.card_actions.move_up | translate"
                      (click)="move(i, -1)">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">arrow_upward</mat-icon>
              </button>
              <button mat-icon-button class="!w-8 !h-8" [disabled]="i === order().length - 1"
                      [matTooltip]="I18N.gallery.card_actions.move_down | translate"
                      [attr.aria-label]="I18N.gallery.card_actions.move_down | translate"
                      (click)="move(i, 1)">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">arrow_downward</mat-icon>
              </button>
            </span>
          </div>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions class="!px-6" align="end">
      <button mat-button (click)="reset()">{{ I18N.gallery.card_actions.reset | translate }}</button>
      <button mat-button (click)="ref.close()">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button color="primary" (click)="save()">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CardActionsDialogComponent {
  protected readonly I18N = I18N;
  protected readonly CARD_ACTION_META = CARD_ACTION_META;
  protected readonly ref = inject(MatDialogRef<CardActionsDialogComponent>);
  private readonly service = inject(CardActionsService);

  private readonly initial = this.service.config();
  protected readonly order = signal<CardActionId[]>([...this.initial.order]);
  protected readonly hidden = signal<Set<CardActionId>>(new Set(this.initial.hidden));

  protected toggle(id: CardActionId, visible: boolean): void {
    this.hidden.update(current => {
      const next = new Set(current);
      if (visible) next.delete(id); else next.add(id);
      return next;
    });
  }

  protected move(index: number, delta: -1 | 1): void {
    this.order.update(order => {
      const next = [...order];
      const target = index + delta;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  protected reset(): void {
    this.order.set([...DEFAULT_CARD_ACTIONS.order]);
    this.hidden.set(new Set(DEFAULT_CARD_ACTIONS.hidden));
  }

  protected save(): void {
    const config: CardActionsConfig = { order: this.order(), hidden: [...this.hidden()] };
    this.service.set(config);
    this.ref.close();
  }
}
