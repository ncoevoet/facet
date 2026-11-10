import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { TabLabelComponent } from './tab-label.component';

@Component({
  imports: [TabLabelComponent],
  template: `<app-tab-label icon="insights" [label]="label" [hint]="hint()" />`,
})
class HostComponent {
  readonly label = 'Correlations';
  readonly hint = signal('');
}

describe('TabLabelComponent', () => {
  const matchMedia = window.matchMedia;
  afterEach(() => { window.matchMedia = matchMedia; });

  async function render(wide: boolean) {
    // A plain function, as in test-setup: a vi.fn would lose its implementation to another spec's restoreAllMocks.
    window.matchMedia = (query: string) => ({ ...matchMedia(query), matches: wide });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const tooltip = fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip);
    return { fixture, tooltip, root: fixture.nativeElement as HTMLElement };
  }

  it('keeps the name as the accessible text and hides it visually only below sm', async () => {
    const { root } = await render(false);
    expect(root.querySelector('mat-icon')?.getAttribute('aria-hidden')).toBe('true');
    const name = root.querySelector('[data-tab-name]')!;
    expect(name.textContent?.trim()).toBe('Correlations');
    expect(name.classList).toContain('max-sm:sr-only');
  });

  it('offers the name as a tooltip only while the name is hidden', async () => {
    const narrow = await render(false);
    expect(narrow.tooltip.message).toBe('Correlations');
    expect(narrow.tooltip.disabled).toBe(false);
    const wide = await render(true);
    expect(wide.tooltip.disabled).toBe(true);
  });

  it('shows a hint at every width instead of the name', async () => {
    const { fixture, tooltip } = await render(true);
    fixture.componentInstance.hint.set('Locked until 10 more comparisons');
    fixture.detectChanges();
    expect(tooltip.message).toBe('Locked until 10 more comparisons');
    expect(tooltip.disabled).toBe(false);
  });
});
