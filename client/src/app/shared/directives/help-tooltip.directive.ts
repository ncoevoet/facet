import { Directive, inject } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

/**
 * An explanation tooltip: shown to the left after a short hover, so passing the
 * pointer over a list of controls does not flash one tooltip after another.
 */
@Directive({
  selector: '[appHelpTip]',
  hostDirectives: [{ directive: MatTooltip, inputs: ['matTooltip: appHelpTip'] }],
})
export class HelpTooltipDirective {
  constructor() {
    const tooltip = inject(MatTooltip);
    tooltip.position = 'left';
    tooltip.showDelay = 600;
  }
}
