import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { StatsComponent } from './stats.component';

describe('statistics category choices at cold startup', () => {
  it('reloads type counts after auth settles while gallery reads are parked', async () => {
    const status = signal<{ authenticated: boolean; user_id: string; login_password_required: boolean } | null>(null);
    const identity = computed(() => status()?.user_id ?? '');
    const auth = { status, identity, isAuthenticated: computed(() => !!status()?.authenticated), isEdition: () => false, token: null };
    const events = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(), provideHttpClientTesting(), GalleryStore, StatsComponent,
      { provide: AuthService, useValue: auth },
      { provide: I18nService, useValue: { t: (key: string) => key, locale: signal('en'), translations: signal({}) } },
      { provide: Router, useValue: { url: '/stats', navigate: vi.fn(), events } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: { get: () => null } } } },
    ] });
    const http = TestBed.inject(HttpTestingController);
    const store = TestBed.inject(GalleryStore);
    const beforeAuth = store.loadTypeCounts();
    const stale = http.expectOne(req => req.url === '/api/type_counts');
    store.parkListingReads();
    TestBed.inject(StatsComponent);
    TestBed.tick();
    status.set({ authenticated: true, user_id: 'owner', login_password_required: false });
    TestBed.tick();
    expect(stale.cancelled).toBe(true);
    await beforeAuth;
    const current = http.expectOne(req => req.url === '/api/type_counts');
    current.flush({ types: [{ id: 'portrait', label: 'Portrait', count: 3 }, { id: 'landscape', label: 'Landscape', count: 2 }] });
    await vi.waitFor(() => expect(store.types().map(t => t.id)).toEqual(['portrait', 'landscape']));
    http.expectOne(req => req.url === '/api/stats/overview').flush('failed', { status: 500, statusText: 'Failed' });
    await Promise.resolve();
    http.verify({ ignoreCancelled: true });
    TestBed.resetTestingModule();
  });
});
