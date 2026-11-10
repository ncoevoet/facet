import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { TimelineReads } from './timeline-reads.service';

describe('TimelineReads', () => {
  function setup() {
    const responses: Subject<unknown>[] = [];
    const api = { get: vi.fn(() => { const response = new Subject<unknown>(); responses.push(response); return response; }) };
    const auth = { token: 'token-a' };
    TestBed.configureTestingModule({ providers: [
      { provide: ApiService, useValue: api }, { provide: AuthService, useValue: auth },
    ] });
    return { reads: TestBed.inject(TimelineReads), api, auth, responses };
  }

  it('sends one request for two views asking for the same scope at once, whatever their key order', () => {
    const { reads, api, responses } = setup();
    const strip = vi.fn(); const calendar = vi.fn();
    reads.get('/timeline/dates', { hide_bursts: '1', year: 2026, month: 11, date_from: '', date_to: '' }).subscribe(strip);
    reads.get('/timeline/dates', { year: 2026, month: 11, hide_bursts: '1' }).subscribe(calendar);
    expect(api.get).toHaveBeenCalledOnce();
    responses[0].next({ dates: [] }); responses[0].complete();
    expect(strip).toHaveBeenCalledWith({ dates: [] });
    expect(calendar).toHaveBeenCalledWith({ dates: [] });
  });

  it('keeps nothing once a read settles, and never shares across scopes or sessions', () => {
    const { reads, api, auth, responses } = setup();
    reads.get('/timeline/years', {}).subscribe();
    responses[0].next({ years: [] }); responses[0].complete();
    reads.get('/timeline/years', {}).subscribe();
    expect(api.get).toHaveBeenCalledTimes(2);
    reads.get('/timeline/years', { date_from: '2026-01-01' }).subscribe();
    expect(api.get).toHaveBeenCalledTimes(3);
    auth.token = 'token-b';
    reads.get('/timeline/years', { date_from: '2026-01-01' }).subscribe();
    expect(api.get).toHaveBeenCalledTimes(4);
  });

  it('keeps the shared read for the view still waiting when the other one cancels, and drops it once nobody waits', () => {
    const { reads, api, responses } = setup();
    const left = reads.get('/timeline/months', { year: 2026 }).subscribe();
    const waiting = vi.fn();
    const right = reads.get('/timeline/months', { year: 2026 }).subscribe(waiting);
    left.unsubscribe();
    responses[0].next({ months: [] });
    expect(waiting).toHaveBeenCalledWith({ months: [] });
    right.unsubscribe();
    reads.get('/timeline/months', { year: 2026 }).subscribe();
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});
