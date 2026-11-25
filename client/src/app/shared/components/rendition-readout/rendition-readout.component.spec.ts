import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { RenditionReadoutComponent } from './rendition-readout.component';

describe('RenditionReadoutComponent', () => {
  function compact() {
    TestBed.configureTestingModule({ imports: [RenditionReadoutComponent], providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(RenditionReadoutComponent);
    fixture.componentRef.setInput('state', { kind: 'source', phase: 'ready', width: 1440, height: 960 });
    fixture.componentRef.setInput('showInfo', false);
    fixture.componentRef.setInput('scale', 1);
    fixture.detectChanges();
    return fixture;
  }

  it('hides healthy source information while keeping zoom and Fit operable', () => {
    const fixture = compact();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[role="status"]')).toBeNull();
    expect(root.textContent).not.toContain('1440');
    const zoom = vi.fn(), fit = vi.fn();
    fixture.componentInstance.zoomStep.subscribe(zoom);
    fixture.componentInstance.fit.subscribe(fit);
    root.querySelector<HTMLButtonElement>('[aria-label="gallery.compare.rendition.zoom_in"]')!.click();
    root.querySelector<HTMLButtonElement>('[data-rendition-fit]')!.click();
    expect(zoom).toHaveBeenCalledExactlyOnceWith(1);
    expect(fit).toHaveBeenCalledOnce();
  });

  it('keeps loading and pending-rendition status visible in compact mode', () => {
    const fixture = compact();
    fixture.componentRef.setInput('pending', true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('photo_detail.rendition.pending');
    fixture.componentRef.setInput('pending', false);
    fixture.componentRef.setInput('state', { kind: 'source', phase: 'loading' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="status"]').textContent).toContain('gallery.compare.rendition.loading');
  });

  for (const fallback of [false, true]) {
    it(`keeps a failed source retry available with fallback=${fallback}, then hides recovered information`, () => {
      const fixture = compact();
      fixture.componentRef.setInput('state', { kind: fallback ? 'thumbnail' : 'source', phase: fallback ? 'ready' : 'failed' });
      fixture.componentRef.setInput('attemptFailed', fallback);
      fixture.detectChanges();
      const root = fixture.nativeElement as HTMLElement;
      const retry = vi.fn(); fixture.componentInstance.retry.subscribe(retry);
      expect(root.querySelector('[role="status"]')).not.toBeNull();
      root.querySelector<HTMLButtonElement>('[data-rendition-retry]')!.click();
      expect(retry).toHaveBeenCalledOnce();
      fixture.componentRef.setInput('attemptFailed', false);
      fixture.componentRef.setInput('state', { kind: 'source', phase: 'ready', width: 1440, height: 960 });
      fixture.detectChanges();
      expect(root.querySelector('[role="status"]')).toBeNull();
      expect(root.querySelector('[data-rendition-retry]')).toBeNull();
    });
  }

  it('reports displayed pixels and offers retry for a failed source attempt', () => {
    TestBed.configureTestingModule({ imports: [RenditionReadoutComponent], providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(RenditionReadoutComponent);
    fixture.componentRef.setInput('state', { kind: 'thumbnail', phase: 'ready', width: 320, height: 240 });
    fixture.componentRef.setInput('attemptFailed', true); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const retry = vi.fn(); fixture.componentInstance.retry.subscribe(retry);
    expect(root.querySelector('[role="status"]')?.textContent).toContain('320 × 240');
    expect(root.textContent).toContain('photo_detail.rendition.attempt_failed');
    const phase = root.querySelector('[role="status"] > span:nth-child(2)')!;
    expect(phase.classList.contains('sr-only')).toBe(true);
    expect(phase.textContent).toContain('gallery.compare.rendition.ready');
    fixture.componentRef.setInput('state', { kind: 'preview', phase: 'loading' }); fixture.detectChanges();
    expect(phase.classList.contains('sr-only')).toBe(false);
    expect(phase.textContent).toContain('gallery.compare.rendition.loading');

    root.querySelector<HTMLButtonElement>('[data-rendition-retry]')!.click();
    expect(retry).toHaveBeenCalledOnce();
    fixture.destroy();
  });
  it('uses the current viewer bounds and emits explicit zoom and Fit actions', () => {
    TestBed.configureTestingModule({ imports: [RenditionReadoutComponent], providers: [
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
    ] });
    const fixture = TestBed.createComponent(RenditionReadoutComponent);
    fixture.componentRef.setInput('state', { kind: 'source', phase: 'ready', width: 1440, height: 960 });
    fixture.componentRef.setInput('minimumScale', 0.5); fixture.componentRef.setInput('maximumScale', 5);
    fixture.componentRef.setInput('scale', 0.5); fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const less = root.querySelector<HTMLButtonElement>('[aria-label="gallery.compare.rendition.zoom_out"]')!;
    const more = root.querySelector<HTMLButtonElement>('[aria-label="gallery.compare.rendition.zoom_in"]')!;
    const zoom = vi.fn(), fit = vi.fn(); fixture.componentInstance.zoomStep.subscribe(zoom); fixture.componentInstance.fit.subscribe(fit);
    expect(less.disabled).toBe(true); expect(more.disabled).toBe(false);
    more.click(); expect(zoom).toHaveBeenCalledExactlyOnceWith(1);
    root.querySelector<HTMLButtonElement>('[data-rendition-fit]')!.click(); expect(fit).toHaveBeenCalledOnce();
    fixture.componentRef.setInput('scale', 5); fixture.detectChanges();
    expect(more.disabled).toBe(true); expect(less.disabled).toBe(false);
    expect(root.querySelector('[data-rendition-fit]')?.getAttribute('aria-label')).toBe('gallery.compare.rendition.fit (5.0×)');
    fixture.destroy();
  });

});
