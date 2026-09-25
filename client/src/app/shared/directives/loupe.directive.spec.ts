import { Component, viewChild } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LoupeDirective, LoupeFit } from './loupe.directive';

@Component({
  selector: 'app-test-host',
  standalone: true,
  imports: [LoupeDirective],
  template: `
    <img #img alt="" [appLoupe]="src" [loupeActive]="active" [loupeZoom]="zoom" [loupeFit]="fit" />
  `,
})
class TestHostComponent {
  src = 'https://example.test/full.jpg';
  active = true;
  zoom = 3;
  fit: LoupeFit = 'fill';
  readonly directive = viewChild(LoupeDirective);
}

describe('LoupeDirective', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<TestHostComponent>>;
  let host: TestHostComponent;
  let img: HTMLImageElement;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [TestHostComponent] });
    fixture = TestBed.createComponent(TestHostComponent);
    host = fixture.componentInstance;
    fixture.detectChanges();
    img = fixture.nativeElement.querySelector('img');
  });

  function fireMove(clientX: number, clientY: number): void {
    img.dispatchEvent(new MouseEvent('mousemove', { clientX, clientY, bubbles: false }));
  }

  function lensDiv(): HTMLDivElement {
    return document.body.querySelector('div[style*="border-radius"]') as HTMLDivElement;
  }

  it('maps against the host rect directly when loupeFit is "fill" (grid-tile behaviour)', () => {
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireMove(100, 100);
    const lens = lensDiv();
    // Host rect IS the content rect: background sized by host width/height * zoom.
    expect(lens.style.backgroundSize).toBe('600px 600px');
  });

  it('maps against the object-fit:contain content rect, pillarbox pane (wide box, tall-ish image)', () => {
    host.fit = 'contain';
    fixture.detectChanges();
    // Pane (host) is 400x200; natural image is 100x150 (portrait, non-square) ->
    // scale = min(400/100, 200/150) = min(4, 1.333) = 1.333, content box =
    // 133.33x200, centred: left inset = (400-133.33)/2 = 133.33, top inset 0.
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 400, height: 200, right: 400, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    Object.defineProperty(img, 'naturalWidth', { value: 100, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 150, configurable: true });

    fireMove(200, 100);
    const lens = lensDiv();
    const size = 300;
    const zoom = host.zoom;
    const scale = Math.min(400 / 100, 200 / 150);
    const contentW = 100 * scale;
    const contentH = 150 * scale;
    const leftInset = (400 - contentW) / 2;
    const topInset = (200 - contentH) / 2;
    expect(lens.style.backgroundSize).toBe(`${contentW * zoom}px ${contentH * zoom}px`);
    const x = 200 - leftInset;
    const y = 100 - topInset;
    expect(lens.style.backgroundPosition).toBe(`${-(x * zoom - size / 2)}px ${-(y * zoom - size / 2)}px`);
  });

  it('maps against the object-fit:contain content rect, letterbox pane (tall box, wide image)', () => {
    host.fit = 'contain';
    fixture.detectChanges();
    // Pane (host) is 200x400; natural image is 150x100 (landscape) ->
    // scale = min(200/150, 400/100) = min(1.333, 4) = 1.333, content box =
    // 200x133.33, centred: left inset 0, top inset = (400-133.33)/2 = 133.33.
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    Object.defineProperty(img, 'naturalWidth', { value: 150, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 100, configurable: true });

    fireMove(100, 200);
    const lens = lensDiv();
    const size = 300;
    const zoom = host.zoom;
    const scale = Math.min(200 / 150, 400 / 100);
    const contentW = 150 * scale;
    const contentH = 100 * scale;
    const leftInset = (200 - contentW) / 2;
    const topInset = (400 - contentH) / 2;
    expect(lens.style.backgroundSize).toBe(`${contentW * zoom}px ${contentH * zoom}px`);
    const x = 100 - leftInset;
    const y = 200 - topInset;
    expect(lens.style.backgroundPosition).toBe(`${-(x * zoom - size / 2)}px ${-(y * zoom - size / 2)}px`);
  });

  it('maps against the object-fit:cover content rect for a non-square image in a square host', () => {
    host.fit = 'cover';
    fixture.detectChanges();
    // Host (face-strip thumbnail) is a square 120x120 box. Natural image is
    // 80x120 (portrait, taller than wide, longest side capped at 120) ->
    // cover scale = max(120/80, 120/120) = max(1.5, 1) = 1.5, content box =
    // 120x180, centred and overflowing: left inset 0, top inset = (120-180)/2 = -30.
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 120, height: 120, right: 120, bottom: 120, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    Object.defineProperty(img, 'naturalWidth', { value: 80, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 120, configurable: true });

    fireMove(60, 60);
    const lens = lensDiv();
    const size = 300;
    const zoom = host.zoom;
    const scale = Math.max(120 / 80, 120 / 120);
    const contentW = 80 * scale;
    const contentH = 120 * scale;
    const leftInset = (120 - contentW) / 2;
    const topInset = (120 - contentH) / 2;
    expect(lens.style.backgroundSize).toBe(`${contentW * zoom}px ${contentH * zoom}px`);
    const x = 60 - leftInset;
    const y = 60 - topInset;
    expect(lens.style.backgroundPosition).toBe(`${-(x * zoom - size / 2)}px ${-(y * zoom - size / 2)}px`);
  });

  it('falls back to the host rect when the image has not loaded yet (naturalWidth/Height still 0)', () => {
    host.fit = 'contain';
    fixture.detectChanges();
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 400, height: 200, right: 400, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    // naturalWidth/naturalHeight default to 0 on a jsdom <img> that never loaded.
    fireMove(100, 100);
    const lens = lensDiv();
    expect(lens.style.backgroundSize).toBe(`${400 * host.zoom}px ${200 * host.zoom}px`);
  });

  it('hides the lens when loupeActive is false', () => {
    host.active = false;
    fixture.detectChanges();
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireMove(50, 50);
    const lens = lensDiv();
    expect(lens?.style.display ?? 'none').toBe('none');
  });

  it('updates the lens background-image immediately on a source change while visible, without a mousemove', () => {
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireMove(100, 100);
    let lens = lensDiv();
    expect(lens.style.backgroundImage).toBe('url("https://example.test/full.jpg")');

    host.src = 'https://example.test/other.jpg';
    fixture.detectChanges();

    lens = lensDiv();
    expect(lens.style.backgroundImage).toBe('url("https://example.test/other.jpg")');
  });

  it('keeps the lens hidden on a source change or image load after the cursor has left', () => {
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
      { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
    );
    fireMove(100, 100);
    img.dispatchEvent(new MouseEvent('mouseleave'));
    expect(lensDiv().style.display).toBe('none');

    host.src = 'https://example.test/other.jpg';
    fixture.detectChanges();
    img.dispatchEvent(new Event('load'));

    expect(lensDiv().style.display).toBe('none');
  });

  it('parents the lens under document.fullscreenElement when set, instead of document.body', () => {
    const fsHost = document.createElement('div');
    document.body.appendChild(fsHost);
    const original = Object.getOwnPropertyDescriptor(Document.prototype, 'fullscreenElement');
    Object.defineProperty(document, 'fullscreenElement', { value: fsHost, configurable: true });
    try {
      vi.spyOn(img, 'getBoundingClientRect').mockReturnValue(
        { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => ({}) } as DOMRect,
      );
      fireMove(50, 50);
      const lens = fsHost.querySelector('div[style*="border-radius"]');
      expect(lens).toBeTruthy();
      expect(lens?.parentElement).toBe(fsHost);
    } finally {
      if (original) Object.defineProperty(document, 'fullscreenElement', original);
      else delete (document as unknown as Record<string, unknown>)['fullscreenElement'];
      fsHost.remove();
    }
  });
});
