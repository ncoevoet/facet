import type { MatDialogConfig } from '@angular/material/dialog';
import type { StackEditorData } from './stack-editor-host';

/** Dialog-only data: the page host owns its Undo channel, so it never travels in StackEditorData. */
export interface StackDialogData extends StackEditorData {
  /** Runs after the stack save is undone; handed to the editor as StackEditorHost.onUndone. */
  onUndone?: () => void;
}

/** Shared by the stack navigator and the suggestion editor. */
export function stackDialogConfig(data: StackDialogData): MatDialogConfig<StackDialogData> {
  return { data, width: '96vw', maxWidth: '1400px', height: '92dvh', maxHeight: '92dvh',
    autoFocus: 'first-header', restoreFocus: true };
}
