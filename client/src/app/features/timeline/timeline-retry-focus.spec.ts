import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { HANDLE_SERVER_ERROR_LOCALLY } from '../../core/utils/http-error-context';
import { GalleryStore } from '../gallery/gallery.store';
import { TimelineFiltersService } from './timeline-filters.service';
import { TimelineMonthsComponent } from './timeline-months.component';
import { TimelineDaysComponent } from './timeline-days.component';

describe('Timeline calendar retry focus', () => {
  async function setup(kind: 'months' | 'days') {
    const api = { get: vi.fn().mockReturnValue(throwError(() => new Error('offline'))) };
    TestBed.configureTestingModule({ providers: [
      provideRouter([]), TimelineFiltersService,
      { provide: ApiService, useValue: api },
      { provide: AuthService, useValue: { status: signal({ user_id: 'alice' }), token: 'a' } },
      { provide: GalleryStore, useValue: { viewFilterParams: signal({}) } },
      { provide: I18nService, useValue: { locale: signal('en'), translations: () => ({}), t: (key: string) => key } },
    ] });
    vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/timeline');
    const fixture = kind === 'months' ? TestBed.createComponent(TimelineMonthsComponent) : TestBed.createComponent(TimelineDaysComponent);
    fixture.componentRef.setInput('year', '2024');
    if (kind === 'days') fixture.componentRef.setInput('month', '6');
    const root = fixture.nativeElement as HTMLElement; document.body.appendChild(root);
    const settle = async () => { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); };
    await settle();
    return { api, fixture, root, settle };
  }

  it.each(['months', 'days'] as const)('restores focus to the empty %s state after retry', async kind => {
    const v = await setup(kind);
    expect(v.api.get.mock.calls[0][2].get(HANDLE_SERVER_ERROR_LOCALLY)).toBe(true);
    const response = new Subject<unknown>(); v.api.get.mockReturnValueOnce(response);
    const retry = v.root.querySelector<HTMLButtonElement>('[data-timeline-retry]')!;
    retry.focus(); retry.click(); await v.settle();
    expect(document.activeElement).toBe(retry);
    response.next(kind === 'months' ? { months: [] } : { dates: [] });
    await v.settle(); await v.settle();
    expect(document.activeElement).toBe(v.root.querySelector('[data-timeline-empty]'));
    expect(document.activeElement?.textContent).toContain(kind === 'months' ? 'timeline.empty' : 'timeline.no_photos_month');
    if (kind === 'days') expect(v.root.querySelector('[role="group"] [disabled]')).not.toBeNull();
    v.fixture.destroy(); v.root.remove();
  });

  it('does not steal focus after a user leaves Retry during a delayed request', async () => {
    const v = await setup('months');
    const response = new Subject<unknown>(); v.api.get.mockReturnValueOnce(response);
    const retry = v.root.querySelector<HTMLButtonElement>('[data-timeline-retry]')!;
    retry.focus(); retry.click(); await v.settle();
    const other = document.createElement('button'); document.body.appendChild(other); other.focus();
    response.next({ months: [] }); await v.settle();
    expect(document.activeElement).toBe(other);
    other.remove(); v.fixture.destroy(); v.root.remove();
  });
});
