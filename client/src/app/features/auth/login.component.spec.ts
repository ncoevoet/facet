import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { LoginComponent } from './login.component';

describe('LoginComponent', () => {
  let component: LoginComponent;
  let mockRouter: { navigate: Mock };
  let mockAuth: {
    isMultiUser: Mock;
    login: Mock;
  };
  let mockI18n: { t: Mock };

  beforeEach(() => {
    mockRouter = { navigate: vi.fn() };
    mockAuth = {
      isMultiUser: vi.fn(() => false),
      login: vi.fn(() => Promise.resolve('ok')),
    };
    mockI18n = { t: vi.fn((key: string) => key) };

    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
      ],
    });
    component = TestBed.runInInjectionContext(() => new LoginComponent());
  });

  describe('initial state', () => {
    it('should have loading as false', () => {
      expect(component.loading()).toBe(false);
    });

    it('should have error as empty string', () => {
      expect(component.error()).toBe('');
    });

    it('should have username as empty string', () => {
      expect(component.username).toBe('');
    });

    it('should have password as empty string', () => {
      expect(component.password).toBe('');
    });
  });

  describe('login()', () => {
    it('should call auth.login with password only in single-user mode', async () => {
      mockAuth.isMultiUser.mockReturnValue(false);
      component.password = 'secret';

      await component.login();

      expect(mockAuth.login).toHaveBeenCalledWith('secret');
    });

    it('should call auth.login with password and username in multi-user mode', async () => {
      mockAuth.isMultiUser.mockReturnValue(true);
      component.username = 'admin';
      component.password = 'secret';

      await component.login();

      expect(mockAuth.login).toHaveBeenCalledWith('secret', 'admin');
    });

    it('should navigate to / on successful login', async () => {
      mockAuth.login.mockResolvedValue('ok');

      await component.login();

      expect(mockRouter.navigate).toHaveBeenCalledWith(['/']);
    });

    it("should set the invalid-credentials message when login reports 'invalid'", async () => {
      mockAuth.login.mockResolvedValue('invalid');

      await component.login();

      expect(component.error()).toBe('auth.invalid_credentials');
      expect(mockI18n.t).toHaveBeenCalledWith('auth.invalid_credentials');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it("should say the config is unreadable when login reports 'unavailable'", async () => {
      // The server produced a 503 and a log line naming the real problem.
      // Telling this operator their credentials are invalid sends them to
      // retype a password that was never wrong.
      mockAuth.login.mockResolvedValue('unavailable');

      await component.login();

      expect(component.error()).toBe('auth.config_unreadable');
      expect(mockI18n.t).toHaveBeenCalledWith('auth.config_unreadable');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it("should say too many requests when login reports 'rate_limited'", async () => {
      // The rate limiter rejected the request before any password check ran,
      // so it is never bad credentials -- retyping one only extends the lockout.
      mockAuth.login.mockResolvedValue('rate_limited');

      await component.login();

      expect(component.error()).toBe('errors.rate_limited');
      expect(mockI18n.t).toHaveBeenCalledWith('errors.rate_limited');
      expect(mockRouter.navigate).not.toHaveBeenCalled();
    });

    it('should set error message when login throws an exception', async () => {
      mockAuth.login.mockRejectedValue(new Error('Network error'));

      await component.login();

      expect(component.error()).toBe('auth.error');
      expect(mockI18n.t).toHaveBeenCalledWith('auth.error');
    });

    it('should set loading to true during the operation', async () => {
      let loadingDuringCall = false;
      mockAuth.login.mockImplementation(() => {
        loadingDuringCall = component.loading();
        return Promise.resolve(true);
      });

      await component.login();

      expect(loadingDuringCall).toBe(true);
    });

    it('should set loading to false after successful login', async () => {
      mockAuth.login.mockResolvedValue('ok');

      await component.login();

      expect(component.loading()).toBe(false);
    });

    it('should set loading to false after failed login', async () => {
      mockAuth.login.mockResolvedValue('invalid');

      await component.login();

      expect(component.loading()).toBe(false);
    });

    it('should set loading to false after login throws', async () => {
      mockAuth.login.mockRejectedValue(new Error('fail'));

      await component.login();

      expect(component.loading()).toBe(false);
    });

    it('should clear previous error before attempting login', async () => {
      mockAuth.login.mockResolvedValue('invalid');
      await component.login();
      expect(component.error()).not.toBe('');

      let errorClearedDuringCall = false;
      mockAuth.login.mockImplementation(() => {
        errorClearedDuringCall = component.error() === '';
        return Promise.resolve('ok');
      });

      await component.login();

      expect(errorClearedDuringCall).toBe(true);
    });
  });
});
