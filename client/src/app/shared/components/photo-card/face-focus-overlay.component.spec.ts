import { signal } from '@angular/core';
import { AuthService } from '../../../core/services/auth.service';
import { FaceOutlinePreferences } from '../../../core/services/face-outline-preferences.service';
import { personOutlineColors } from '../../utils/person-outline-colors';
import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { FaceFocusOverlayComponent } from './face-focus-overlay.component';
import { PersonFaceBoxesService } from './person-face-boxes.service';

/** Answer a face_boxes POST: one box for every path asked, the second one nothing. */
function answer(boxes: Record<string, number[][]>) {
  return (_url: string, body: { paths: string[] }) =>
    of({ boxes: Object.fromEntries(body.paths.filter((p) => p in boxes).map((p) => [p, boxes[p]])) });
}

describe('FaceFocusOverlayComponent', () => {
  let fixture: ComponentFixture<FaceFocusOverlayComponent>;
  let mockApi: { get: Mock; post: Mock };

  function create(path: string, personId: string, cover = false): ComponentFixture<FaceFocusOverlayComponent> {
    const f = TestBed.createComponent(FaceFocusOverlayComponent);
    f.componentRef.setInput('path', path);
    f.componentRef.setInput('personId', personId);
    f.componentRef.setInput('imageWidth', 1000);
    f.componentRef.setInput('imageHeight', 500);
    f.componentRef.setInput('cover', cover);
    return f;
  }

  async function settle(...fixtures: ComponentFixture<FaceFocusOverlayComponent>[]) {
    for (const f of fixtures) f.detectChanges();
    await Promise.all(fixtures.map((f) => f.whenStable()));
    await new Promise((r) => setTimeout(r));
    for (const f of fixtures) f.detectChanges();
  }

  async function render(personId: string, cover = false) {
    fixture = create('/p/a.jpg', personId, cover);
    await settle(fixture);
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(), post: vi.fn(answer({ '/p/a.jpg': [[0.1, 0.2, 0.3, 0.6]] })) };
    TestBed.configureTestingModule({
      imports: [FaceFocusOverlayComponent],
      providers: [{ provide: ApiService, useValue: mockApi }],
    });
  });

  it('outlines the filtered person, in the photo pixel frame', async () => {
    await render('95');
    expect(mockApi.post).toHaveBeenCalledWith('/person/95/face_boxes', { paths: ['/p/a.jpg'] });
    expect(mockApi.get).not.toHaveBeenCalled();
    const rects = [...fixture.nativeElement.querySelectorAll('rect')] as SVGRectElement[];
    expect(rects.length).toBe(1);
    expect(['x', 'y', 'width', 'height'].map((a) => Math.round(Number(rects[0].getAttribute(a)))))
      .toEqual([100, 100, 200, 200]);
    expect(rects[0].getAttribute('stroke')).toBe(personOutlineColors('95').get(95));
    expect(fixture.nativeElement.querySelector('svg').getAttribute('viewBox')).toBe('0 0 1000 500');
  });

  it('crops like an object-cover thumbnail when the tile is filled', async () => {
    await render('95', true);
    expect(fixture.nativeElement.querySelector('svg').getAttribute('preserveAspectRatio')).toBe('xMidYMid slice');
  });

  it('asks nothing and draws nothing without a person filter', async () => {
    await render('');
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();

  });

  it('draws nothing when the server has no box for the photo', async () => {
    mockApi.post.mockImplementation(answer({}));
    await render('95');
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
  });

  it('draws nothing when the request fails', async () => {
    mockApi.post.mockReturnValue(throwError(() => new Error('down')));
    await render('95');
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
  });

  it('draws matching colors for every selected person and toggles without fetching photos', async () => {
    await render('95,163');
    const colors = personOutlineColors('95,163');
    expect(mockApi.post.mock.calls.map(c => c[0])).toEqual(['/person/95/face_boxes', '/person/163/face_boxes']);
    expect([...fixture.nativeElement.querySelectorAll('rect')].map((r: any) => r.getAttribute('stroke'))).toEqual([...colors.values()]);
    const preference = TestBed.inject(FaceOutlinePreferences);
    preference.setEnabled(false); await settle(fixture);
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
    preference.setEnabled(true); await settle(fixture);
    expect(fixture.nativeElement.querySelectorAll('rect')).toHaveLength(2);
    expect(mockApi.post).toHaveBeenCalledTimes(2);
    expect(mockApi.get).not.toHaveBeenCalled();
  });

  it('does not cap supported people at the palette size', async () => {
    const ids = Array.from({length: 11}, (_, i) => i + 1).join(',');
    await render(ids);
    expect(mockApi.post).toHaveBeenCalledTimes(11);
    expect(fixture.nativeElement.querySelectorAll('rect')).toHaveLength(11);
    expect(personOutlineColors(ids).size).toBe(11);
  });

  it('twenty tiles share ONE request, and each draws its own box', async () => {
    const paths = Array.from({ length: 20 }, (_, i) => `/p/${i}.jpg`);
    mockApi.post.mockImplementation(answer(Object.fromEntries(paths.map((p, i) => [p, [[i / 100, 0, i / 100 + 0.1, 0.5]]]))));
    const fixtures = paths.map((p) => create(p, '95'));

    await settle(...fixtures);

    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(mockApi.post.mock.calls[0][1].paths).toEqual(paths);
    expect(fixtures.every((f) => f.nativeElement.querySelectorAll('rect').length === 1)).toBe(true);
    expect(Number(fixtures[7].nativeElement.querySelector('rect').getAttribute('x'))).toBeCloseTo(70);
  });
});

describe('PersonFaceBoxesService', () => {
  let service: PersonFaceBoxesService;
  let mockApi: { post: Mock };

  beforeEach(() => {
    mockApi = { post: vi.fn((_url: string, body: { paths: string[] }) =>
      of({ boxes: Object.fromEntries(body.paths.map((p) => [p, [[0, 0, 1, 1]]])) })) };
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: mockApi }] });
    service = TestBed.inject(PersonFaceBoxesService);
  });

  it('settles every caller even when pending work exceeds the settled-cache limit', async () => {
    const original = service.boxes(5, '/p/first.jpg');
    const work = Array.from({length: 4001}, (_, i) => service.boxes(5, `/p/${i}.jpg`));
    const repeated = service.boxes(5, '/p/first.jpg');
    expect(repeated).toBe(original);
    const answers = await Promise.all([original, ...work, repeated]);
    expect(answers.every(boxes => boxes.length === 1)).toBe(true);
    expect((service as any).cache.size).toBeLessThanOrEqual(4000);
    expect((service as any).inFlight.size).toBe(0);
  });

  it('splits a batch above the 200-path cap', async () => {
    await Promise.all(Array.from({ length: 450 }, (_, i) => service.boxes(5, `/p/${i}.jpg`)));
    expect(mockApi.post.mock.calls.map((c) => c[1].paths.length)).toEqual([200, 200, 50]);
  });

  it('answers a repeated path from the cache, and asks again for another person', async () => {
    await service.boxes(5, '/p/a.jpg');
    await service.boxes(5, '/p/a.jpg');
    expect(mockApi.post).toHaveBeenCalledTimes(1);
    await service.boxes(6, '/p/a.jpg');
    await service.boxes(5, '/p/a.jpg');
    expect(mockApi.post.mock.calls.map((c) => c[0])).toEqual([
      '/person/5/face_boxes', '/person/6/face_boxes',
    ]);
  });
});

describe('PersonFaceBoxesService invalidation', () => {
  let service: PersonFaceBoxesService;
  let mockApi: { post: Mock };

  beforeEach(() => {
    mockApi = { post: vi.fn(() => of({ boxes: {} })) };
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: mockApi }] });
    service = TestBed.inject(PersonFaceBoxesService);
  });

  it('re-fetches a path after invalidate, and keeps the other paths cached', async () => {
    await Promise.all([service.boxes(5, '/p/a.jpg'), service.boxes(5, '/p/b.jpg')]);
    service.invalidate('/p/a.jpg');
    await Promise.all([service.boxes(5, '/p/a.jpg'), service.boxes(5, '/p/b.jpg')]);
    expect(mockApi.post.mock.calls.map((c) => c[1].paths)).toEqual([['/p/a.jpg', '/p/b.jpg'], ['/p/a.jpg']]);
  });

  it('re-fetches everything after clear', async () => {
    await service.boxes(5, '/p/a.jpg');
    service.clear();
    await service.boxes(5, '/p/a.jpg');
    expect(mockApi.post).toHaveBeenCalledTimes(2);
  });
});


describe('Person face box ownership and retry', () => {
  const identity = signal('first');
  let service: PersonFaceBoxesService;
  let post: Mock;
  beforeEach(() => {
    identity.set('first');
    post = vi.fn();
    TestBed.configureTestingModule({providers: [
      {provide: AuthService, useValue: {identity}}, {provide: ApiService, useValue: {post}},
    ]});
    service = TestBed.inject(PersonFaceBoxesService);
  });

  it('does not dispatch a queued account A batch using account B credentials', async () => {
    post.mockReturnValue(of({boxes: {'/a': [[0, 0, 0.1, 0.1]]}}));
    const queued = service.boxes(5, '/a');
    identity.set('second');
    expect(await queued).toEqual([]);
    expect(post).not.toHaveBeenCalled();
    identity.set('first');
    post.mockReturnValueOnce(of({boxes: {'/a': [[0, 0, 1, 1]]}}));
    expect(await service.boxes(5, '/a')).toEqual([[0, 0, 1, 1]]);
  });

  it('rejects a previous account completion and re-reads the same photo', async () => {
    const old = new Subject<any>(); post.mockReturnValueOnce(old);
    const first = service.boxes(5, '/a'); await Promise.resolve();
    identity.set('second');
    post.mockReturnValueOnce(of({boxes: {'/a': [[0, 0, 1, 1]]}}));
    const second = service.boxes(5, '/a');
    old.next({boxes: {'/a': [[0, 0, 0.1, 0.1]]}}); old.complete();
    expect(await first).toEqual([]);
    expect(await second).toEqual([[0, 0, 1, 1]]);
  });

  it('invalidation for all people refuses old work without deleting a newer retry', async () => {
    const old = new Subject<any>(); post.mockReturnValue(old);
    const first = service.boxes(5, '/a'); const other = service.boxes(6, '/a');
    await Promise.resolve(); service.invalidate('/a');
    post.mockReturnValue(of({boxes: {'/a': [[0, 0, 1, 1]]}}));
    const fresh = service.boxes(5, '/a');
    old.error(new Error('old request failed'));
    expect(await first).toEqual([]); expect(await other).toEqual([]);
    expect(await fresh).toEqual([[0, 0, 1, 1]]);
    expect(service.boxes(5, '/a')).toBe(fresh);
  });

  it('permits retry after a failure and releases pending ownership', async () => {
    post.mockReturnValueOnce(throwError(() => new Error('offline')));
    expect(await service.boxes(5, '/a')).toEqual([]);
    expect((service as any).inFlight.size).toBe(0);
    post.mockReturnValueOnce(of({boxes: {'/a': [[0, 0, 1, 1]]}}));
    expect(await service.boxes(5, '/a')).toEqual([[0, 0, 1, 1]]);
  });
});
