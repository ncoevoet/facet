import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';

@Component({
  selector: 'app-login',
  imports: [
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    TranslatePipe,
  ],
  template: `
    <div class="flex items-center justify-center min-h-full p-4">
      <mat-card class="w-full max-w-sm">
        <mat-card-header>
          <mat-card-title class="!flex items-center gap-2">
            <mat-icon>diamond</mat-icon>
            Facet
          </mat-card-title>
        </mat-card-header>
        <mat-card-content class="mt-4">
          @if (auth.isMultiUser()) {
            <mat-form-field class="w-full">
              <mat-label>{{ 'auth.username' | translate }}</mat-label>
              <input matInput [(ngModel)]="username" (keyup.enter)="login()" />
            </mat-form-field>
          }
          <mat-form-field class="w-full">
            <mat-label>{{ 'auth.password' | translate }}</mat-label>
            <input matInput type="password" [(ngModel)]="password" (keyup.enter)="login()" />
          </mat-form-field>
          @if (error()) {
            <p class="text-red-400 text-sm mt-1">{{ error() }}</p>
          }
        </mat-card-content>
        <mat-card-actions class="!px-4 !pb-4">
          <button mat-flat-button class="w-full" [disabled]="loading()" (click)="login()">
            {{ 'auth.login' | translate }}
          </button>
        </mat-card-actions>
      </mat-card>
    </div>
  `,
})
export class LoginComponent {
  private router = inject(Router);
  auth = inject(AuthService);
  private i18n = inject(I18nService);

  username = '';
  password = '';
  loading = signal(false);
  error = signal('');

  async login(): Promise<void> {
    this.loading.set(true);
    this.error.set('');

    try {
      const success = this.auth.isMultiUser()
        ? await this.auth.login(this.password, this.username)
        : await this.auth.login(this.password);

      if (success) {
        this.router.navigate(['/']);
      } else {
        this.error.set(this.i18n.t('auth.invalid_credentials'));
      }
    } catch {
      this.error.set(this.i18n.t('auth.error'));
    } finally {
      this.loading.set(false);
    }
  }
}
