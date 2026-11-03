import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { RenditionReadoutComponent } from './rendition-readout.component';

describe('RenditionReadoutComponent', () => {
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
    root.querySelector<HTMLButtonElement>('[data-rendition-retry]')!.click();
    expect(retry).toHaveBeenCalledOnce();
    fixture.destroy();
  });
});
