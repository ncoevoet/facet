import { TestBed } from '@angular/core/testing';
import { ScanShowcaseComponent, SHOWCASE_PHOTOS } from './scan-showcase.component';

describe('ScanShowcaseComponent', () => {
  function render(photos: { path: string }[]) {
    const fixture = TestBed.createComponent(ScanShowcaseComponent);
    fixture.componentRef.setInput('photos', photos);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('keeps its shape with placeholder tiles until photos arrive', () => {
    const root = render([]);
    const tiles = root.querySelectorAll('.grid > div');
    expect(tiles).toHaveLength(SHOWCASE_PHOTOS);
    expect(root.querySelectorAll('img')).toHaveLength(0);
    expect([...tiles].every(tile => tile.classList.contains('animate-pulse'))).toBe(true);
  });

  it('puts the newest photo in the large tile and lays out no more than fits', () => {
    const photos = Array.from({ length: SHOWCASE_PHOTOS + 2 }, (_, i) => ({ path: `/p/${i}.jpg` }));
    const root = render(photos);
    const images = [...root.querySelectorAll('img')];
    expect(images).toHaveLength(SHOWCASE_PHOTOS);
    expect(decodeURIComponent(images[0].getAttribute('src')!)).toContain('/p/0.jpg');
    const tiles = [...root.querySelectorAll('.grid > div')];
    expect(tiles[0].classList.contains('col-span-2')).toBe(true);
    expect(tiles[1].classList.contains('col-span-2')).toBe(false);
    // The hero fades in AND drifts, so the two animations sit on different elements.
    expect(images[0].classList.contains('animate-scan-photo-in')).toBe(true);
    expect(images[0].classList.contains('animate-scan-drift')).toBe(false);
    expect(images[0].parentElement!.classList.contains('animate-scan-drift')).toBe(true);
    expect(images[1].parentElement!.classList.contains('animate-scan-drift')).toBe(false);
    expect(root.querySelector('.animate-pulse')).toBeNull();
  });

  it('is hidden from assistive technology', () => {
    const fixture = TestBed.createComponent(ScanShowcaseComponent);
    fixture.componentRef.setInput('photos', []);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).getAttribute('aria-hidden')).toBe('true');
  });
});
