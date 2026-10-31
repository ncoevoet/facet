import type { MatAutocompleteTrigger } from '@angular/material/autocomplete';

/**
 * Keeps an Enter that picked an autocomplete option from also submitting the input.
 * The autocomplete takes the option on the keydown; the keyup that follows would
 * otherwise save the text before the pick has landed. Wire ``down`` to
 * ``(keydown.enter)`` and ``up`` to ``(keyup.enter)``: submit only when ``up`` is true.
 */
export class EnterPickGuard {
  private picked = false;

  /** Remember whether this Enter keydown picks the highlighted option of an open panel. */
  down(trigger: Pick<MatAutocompleteTrigger, 'panelOpen' | 'activeOption'> | null | undefined): void {
    this.picked = !!trigger?.panelOpen && !!trigger.activeOption;
  }

  /** True when the Enter keyup should submit; false (once) when its keydown picked an option. */
  up(): boolean {
    const submit = !this.picked;
    this.picked = false;
    return submit;
  }
}
