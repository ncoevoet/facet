import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';

export interface RecomputeResult {
  success: boolean;
  message?: string;
}

@Injectable({ providedIn: 'root' })
export class CategoryRecomputeService {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);

  async recomputeCategory(category: string): Promise<RecomputeResult | null> {
    try {
      return await firstValueFrom(
        this.api.post<RecomputeResult>('/stats/categories/recompute', { category }),
      );
    } catch {
      this.snackBar.open(this.i18n.t(I18N.comparison.error_recalculating), '', { duration: 4000 });
      return null;
    }
  }
}
