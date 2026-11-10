import { describe, expect, it } from 'vitest';
import { MAT_SNACK_BAR_DEFAULT_OPTIONS, MatSnackBarConfig } from '@angular/material/snack-bar';
import { appConfig } from './app.config';
import { SNACKBAR_LIFT_CLASS } from './shared/utils/mobile-bar';

describe('appConfig', () => {
  it('lifts every snackbar above the bottom bars by default, so no caller has to', () => {
    const provider = appConfig.providers.find(
      (p): p is { provide: unknown; useValue: MatSnackBarConfig } => typeof p === 'object' && p !== null && 'provide' in p && p.provide === MAT_SNACK_BAR_DEFAULT_OPTIONS,
    );
    expect(provider?.useValue.panelClass).toEqual([SNACKBAR_LIFT_CLASS]);
  });
});
