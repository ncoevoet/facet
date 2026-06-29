import { signal } from '@angular/core';
import { isTypingContext } from './keyboard';

/** Shared hover-loupe state (Photo-Mechanic-style Z toggle + zoom level) for the
 *  Scenes and culling contact strips: the two state signals plus a key handler
 *  that flips the loupe unless the user is typing. */
export function createLoupeState() {
  const loupeActive = signal(false);
  const loupeZoom = signal(3);

  function toggle(event: Event): void {
    if (isTypingContext(event)) return;
    event.preventDefault();
    loupeActive.set(!loupeActive());
  }

  return { loupeActive, loupeZoom, toggle };
}
