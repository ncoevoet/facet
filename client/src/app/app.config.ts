import {
  ApplicationConfig,
  ErrorHandler,
  isDevMode,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
} from '@angular/core';
import { provideServiceWorker } from '@angular/service-worker';
import { provideRouter, RouteReuseStrategy, TitleStrategy, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { MAT_DATE_LOCALE, provideNativeDateAdapter } from '@angular/material/core';
import { MAT_SNACK_BAR_DEFAULT_OPTIONS, MatSnackBarConfig } from '@angular/material/snack-bar';

import { routes } from './app.routes';
import { GalleryReuseStrategy } from './core/gallery-reuse.strategy';
import { I18nTitleStrategy } from './core/i18n-title.strategy';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { errorInterceptor } from './core/interceptors/error.interceptor';
import { retryInterceptor } from './core/interceptors/retry.interceptor';
import { provideAgentTools } from './core/agent/agent-tools.bootstrap';
import { GlobalErrorHandler } from './core/services/global-error-handler.service';
import { SNACKBAR_LIFT_CLASS } from './shared/utils/mobile-bar';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes, withComponentInputBinding(), withInMemoryScrolling({ scrollPositionRestoration: 'top' })),
    { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
    { provide: TitleStrategy, useExisting: I18nTitleStrategy },
    provideHttpClient(withXhr(), withInterceptors([authInterceptor, errorInterceptor, retryInterceptor])),
    provideAnimations(),
    { provide: MAT_DATE_LOCALE, useValue: 'en-GB' },
    { provide: MAT_SNACK_BAR_DEFAULT_OPTIONS, useValue: { panelClass: [SNACKBAR_LIFT_CLASS] } satisfies MatSnackBarConfig },
    provideNativeDateAdapter(),
    { provide: ErrorHandler, useClass: GlobalErrorHandler },
    provideAgentTools(),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
