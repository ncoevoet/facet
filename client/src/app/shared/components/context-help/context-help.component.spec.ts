import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { ContextHelpComponent } from './context-help.component';

describe('ContextHelpComponent', () => {
  it('reveals explanations only on request and restores focus for Close and Escape', () => {
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
    const help = root.querySelector('details')!;
    const trigger = root.querySelector('summary')!;
    expect(root.textContent).not.toContain('Display pixels, not RAW sensor pixels');
    for (const dismissal of ['Close', 'Escape']) {
      help.open = true;
      help.dispatchEvent(new Event('toggle'));
      fixture.detectChanges();
      expect(root.textContent).toContain('Display pixels, not RAW sensor pixels');
      const button = root.querySelector<HTMLButtonElement>('[data-context-help-close]')!;
      button.focus();
      if (dismissal === 'Close') button.click();
      else {
        const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
        button.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
      }
      fixture.detectChanges();
      expect(help.open).toBe(false);
      expect(document.activeElement).toBe(trigger);
      expect(root.textContent).not.toContain('Display pixels, not RAW sensor pixels');
    }
    fixture.destroy();
    root.remove();
  });
});
