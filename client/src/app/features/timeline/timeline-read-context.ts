import { HttpContext } from '@angular/common/http';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';

/** Timeline renders its own retry state; retain authentication and crash reporting. */
export function timelineReadContext(): HttpContext {
  return new HttpContext().set(HANDLE_SERVER_ERROR_LOCALLY, true);
}
