import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { PhotoObjectLayerComponent } from './photo-object-layer.component';

describe('PhotoObjectLayerComponent', () => {
  const objects = [{ id: 1, label: 'cake', box: [0.1, 0.2, 0.5, 0.6] }];
  let api: { get: ReturnType<typeof vi.fn> };

  function render(revision = 0) {
    api = { get: vi.fn(() => of({ objects })) };
    TestBed.configureTestingModule({ providers: [
      { provide: ApiService, useValue: api },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
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

  it('reports a failed read, keeps a failed retry visible, and recovers the boxes', async () => {
    const fixture = render();
    api.get.mockReturnValue(throwError(() => new Error('network')));
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const error = () => fixture.nativeElement.querySelector('[role="alert"] button');
    expect(error()).not.toBeNull();
    error().click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(error()).not.toBeNull();
    api.get.mockReturnValue(of({ objects }));
    error().click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(3);
    expect(error()).toBeNull();
    expect(fixture.nativeElement.querySelector('text').textContent.trim()).toBe('cake');
  });

  for (const outcome of ['success', 'failure'] as const) {
    it(`ignores a previous photo's late ${outcome}`, async () => {
      const fixture = render();
      const old = new Subject<{ objects: typeof objects }>();
      api.get.mockReturnValueOnce(old);
      fixture.detectChanges();
      fixture.componentRef.setInput('path', '/b.jpg');
      fixture.detectChanges();
      await fixture.whenStable();
      if (outcome === 'success') old.next({ objects: [{ ...objects[0], label: 'stale' }] });
      else old.error(new Error('old request failed'));
      // Drain both the firstValueFrom rejection and the following catch.
      await Promise.resolve();
      await Promise.resolve();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('text')?.textContent.trim()).toBe('cake');
      expect(fixture.nativeElement.querySelector('[role="alert"]')).toBeNull();
    });
  }

  it('clears the previous boxes while the next photo is loading', async () => {
    const fixture = render();
    fixture.detectChanges();
    await fixture.whenStable();
    const pending = new Subject<{ objects: typeof objects }>();
    api.get.mockReturnValue(pending);
    fixture.componentRef.setInput('path', '/b.jpg');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('rect')).toBeNull();
    pending.next({ objects: [{ ...objects[0], label: 'new' }] });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('text').textContent.trim()).toBe('new');
  });

  it('ignores an older revision response for the same photo', async () => {
    const fixture = render();
    const old = new Subject<{ objects: typeof objects }>();
    api.get.mockReturnValueOnce(old);
    fixture.detectChanges();
    fixture.componentRef.setInput('revision', 1);
    fixture.detectChanges();
    await fixture.whenStable();
    old.next({ objects: [{ ...objects[0], label: 'stale' }] });
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('text').textContent.trim()).toBe('cake');
  });

  it('ignores a response after destruction', async () => {
    const fixture = render();
    const pending = new Subject<{ objects: typeof objects }>();
    api.get.mockReturnValue(pending);
    fixture.detectChanges();
    fixture.destroy();
    pending.next({ objects });
    await Promise.resolve();
    expect(fixture.componentInstance.objects()).toEqual([]);
  });
  it('keeps the boxes visible while a same-path revision reread is pending, and clears them for a new path', async () => {
    const fixture = render();
    fixture.detectChanges();
    await fixture.whenStable();
    const pending = new Subject<{ objects: typeof objects }>();
    api.get.mockReturnValue(pending);
    fixture.componentRef.setInput('revision', 1);
    fixture.detectChanges();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(fixture.nativeElement.querySelector('rect')).not.toBeNull();
    fixture.componentRef.setInput('path', '/b.jpg');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('rect')).toBeNull();
  });

});
