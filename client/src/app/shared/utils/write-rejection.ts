import { HttpErrorResponse } from '@angular/common/http';

/** True when a failed write was refused outright (a 4xx answer), so it cannot have committed. Anything
 *  else -- a 5xx, a dropped connection, a timeout -- leaves the outcome uncertain, and the caller must
 *  lock the action and read the server's state back before offering it again. */
export function isDefinitiveRejection(error: unknown): boolean {
  return error instanceof HttpErrorResponse && error.status >= 400 && error.status < 500;
}
