import { OverlayContainer } from '@angular/cdk/overlay';
import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { ContextHelpComponent } from './context-help.component';

describe('ContextHelpComponent', () => {
  it('reveals explanations without layout expansion and restores focus for Close, Escape and outside click', async () => {
    TestBed.configureTestingModule({
      imports: [ContextHelpComponent],
      providers: [{ provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } }],
    });
    const fixture = TestBed.createComponent(ContextHelpComponent);
    fixture.componentRef.setInput('label', 'About display images');
    fixture.componentRef.setInput('keys', ['Display pixels, not RAW sensor pixels']);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    document.body.appendChild(root);
    const trigger = root.querySelector('button')!;
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    expect(root.textContent).not.toContain('Display pixels, not RAW sensor pixels');
    for (const dismissal of ['Close', 'Escape', 'Outside']) {
      trigger.focus(); trigger.click(); fixture.detectChanges(); await fixture.whenStable();
      expect(root.textContent).not.toContain('Display pixels, not RAW sensor pixels');
      expect(overlay.textContent).toContain('Display pixels, not RAW sensor pixels');
      const button = overlay.querySelector<HTMLButtonElement>('[role="dialog"] button')!;
      button.focus();
      if (dismissal === 'Close') button.click();
      else if (dismissal === 'Outside') overlay.querySelector<HTMLElement>('.cdk-overlay-backdrop')!.click();
      else {
        const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
        button.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
      }
      fixture.detectChanges();
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
      expect(overlay.querySelector('[role="dialog"]')).toBeNull();
      expect(document.activeElement).toBe(trigger);
      expect(root.textContent).not.toContain('Display pixels, not RAW sensor pixels');
    }
    fixture.destroy();
    root.remove();
  });
});
