import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { PhotoObjectLayerComponent } from './photo-object-layer.component';

describe('PhotoObjectLayerComponent', () => {
  const objects = [{ id: 1, label: 'cake', box: [0.1, 0.2, 0.5, 0.6] }];
  let api: { get: ReturnType<typeof vi.fn> };

  function render(revision = 0) {
    api = { get: vi.fn(() => of({ objects })) };
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: api }] });
    const fixture = TestBed.createComponent(PhotoObjectLayerComponent);
    fixture.componentRef.setInput('path', '/a.jpg');
    fixture.componentRef.setInput('imageWidth', 1000);
    fixture.componentRef.setInput('imageHeight', 500);
    fixture.componentRef.setInput('revision', revision);
    return fixture;
  }

  it('draws each object as a labelled box in the photo frame', async () => {
    const fixture = render();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(api.get).toHaveBeenCalledWith('/photo/objects', { path: '/a.jpg' });
    const rect = fixture.nativeElement.querySelector('rect') as SVGRectElement;
    const [x, y, w, h] = ['x', 'y', 'width', 'height'].map((a) => Number(rect.getAttribute(a)));
    expect(x).toBeCloseTo(100);
    expect(y).toBeCloseTo(100);
    expect(w).toBeCloseTo(400);
    expect(h).toBeCloseTo(200);
    expect(fixture.nativeElement.querySelector('text').textContent.trim()).toBe('cake');
    expect(fixture.nativeElement.classList).toContain('pointer-events-none');
  });

  it('re-reads the objects when the revision changes', async () => {
    const fixture = render();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.componentRef.setInput('revision', 1);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});
