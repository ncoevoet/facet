import { ChangeDetectionStrategy, Component, inject, viewChild } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { StackEditorComponent } from './stack-editor.component';
import { STACK_EDITOR_HOST, StackEditorHost, SKIP_SUGGESTION } from './stack-editor-host';
import type { StackDialogData } from './stack-dialog.config';

/** A dialog result: saved -> true, skip -> the skip sentinel, plain close -> undefined. */
function closeResult(result: 'saved' | 'skip' | 'close'): true | typeof SKIP_SUGGESTION | undefined {
  if (result === 'saved') return true;
  return result === 'skip' ? SKIP_SUGGESTION : undefined;
}

/** A real Material host; mutation state belongs to the shared editor. */
@Component({
  selector: 'app-stack-dialog',
  imports: [StackEditorComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col h-full min-h-0 min-w-0' },
  providers: [{ provide: STACK_EDITOR_HOST, useFactory: (): StackEditorHost => {
    const ref = inject(MatDialogRef<StackDialogComponent>);
    const data = inject<StackDialogData>(MAT_DIALOG_DATA);
    return { data, presentation: 'dialog', keydown$: ref.keydownEvents(), closing$: ref.beforeClosed(),
      onUndone: data.onUndone,
      setBusy: busy => { ref.disableClose = busy; },
      finish: result => ref.close(closeResult(result)),
      invalidate: () => ref.close(),
    };
  } }],
  template: '<app-stack-editor class="flex-1 min-h-0" />',
})
export class StackDialogComponent {
  readonly editor = viewChild.required(StackEditorComponent);
}
