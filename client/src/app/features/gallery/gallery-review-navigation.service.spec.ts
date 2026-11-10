import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '../../core/services/auth.service';
import { GalleryReviewNavigationService } from './gallery-review-navigation.service';

describe('GalleryReviewNavigationService', () => {
  it('starts off, invalidates pending choices and resets at credential boundaries', () => {
    const status = signal({ user_id: 'editor' });
    const edition = signal(true);
    let token = 'first';
    TestBed.configureTestingModule({ providers: [{ provide: AuthService, useValue: {
      status, identity: () => status().user_id, isEdition: edition, get token() { return token; },
    } }] });
    const policy = TestBed.inject(GalleryReviewNavigationService);
    expect(policy.enabled()).toBe(false);
    const off = policy.capture();
    policy.setEnabled(true);
    expect(off()).toBe(false);
    const on = policy.capture();
    expect(on()).toBe(true);
    policy.setEnabled(false); policy.setEnabled(true);
    expect(on()).toBe(false);
    const credential = policy.capture();
    token = 'second';
    expect(credential()).toBe(false);
    expect(policy.enabled()).toBe(false);
    policy.setEnabled(true);
    edition.set(false);
    TestBed.tick();
    expect(policy.enabled()).toBe(false);
    policy.setEnabled(true);
    expect(policy.enabled()).toBe(false);
  });
});
