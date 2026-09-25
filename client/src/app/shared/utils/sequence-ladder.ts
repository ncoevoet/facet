import { HttpErrorResponse } from '@angular/common/http';

/**
 * True when a `SequenceOverrideService.set` rejection is the server refusing to
 * force a `bracket` kind because the frames are not a ladder (a 400), rather
 * than a generic failure. Shared by the gallery's `markAsPanorama` and the
 * culling darkroom's `correctSequence` so both classify the same server error
 * the same way -- a caller of either wants the ladder-specific message only
 * for that one rejection, never for an unrelated failure that happens to share
 * the `bracket` kind.
 */
export function isBracketLadderRejection(kind: string | undefined, error: unknown): boolean {
  return kind === 'bracket' && error instanceof HttpErrorResponse && error.status === 400;
}
