import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
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
    expect(rects[0].getAttribute('stroke')).toBe('#ef4444');
    expect(fixture.nativeElement.querySelector('svg').getAttribute('viewBox')).toBe('0 0 1000 500');
  });

  it('crops like an object-cover thumbnail when the tile is filled', async () => {
    await render('95', true);
    expect(fixture.nativeElement.querySelector('svg').getAttribute('preserveAspectRatio')).toBe('xMidYMid slice');
  });

  it('asks nothing and draws nothing without a single-person filter', async () => {
    await render('');
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
    await render('95,163');
    expect(mockApi.post).not.toHaveBeenCalled();
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
      '/person/5/face_boxes', '/person/6/face_boxes', '/person/5/face_boxes',
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
