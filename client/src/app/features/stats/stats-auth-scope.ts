import { computed, Signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';

/**
 * What scopes Statistics data: who is signed in and with which token. `status()` is replaced on every
 * refresh (an edition unlock, any 403, another tab), so reading it directly would reload every read and
 * wipe a loaded correlation chart for data that did not change. The string only changes with the scope.
 */
export function statsAuthScope(auth: AuthService): Signal<string> {
  return computed(() => {
    auth.status();
    return `${auth.identity()}|${auth.token ?? ''}`;
  });
}
