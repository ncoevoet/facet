import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const snackBar = inject(MatSnackBar);
  const i18n = inject(I18nService);

  return next(req).pipe(
    catchError(error => {
      if (error.status === 401 && !req.url.includes('/api/auth/')) {
        auth.logout();
      } else if (error.status === 429) {
        snackBar.open(i18n.t('errors.rate_limited'), '', { duration: 5000 });
      } else if (error.status === 403 && !req.url.includes('/api/auth/')) {
        snackBar.open(i18n.t('errors.access_denied'), '', { duration: 3000 });
      } else if (error.status >= 500) {
        snackBar.open(i18n.t('errors.server_error'), '', { duration: 3000 });
      }
      return throwError(() => error);
    }),
  );
};
