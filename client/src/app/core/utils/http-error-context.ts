import { HttpContextToken } from '@angular/common/http';

/** The caller renders its own 5xx recovery UI; authentication and crash reporting remain global. */
export const HANDLE_SERVER_ERROR_LOCALLY = new HttpContextToken<boolean>(() => false);
