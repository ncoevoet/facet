import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { COMPACT_PAGE_TABS, TabLabelComponent } from './tab-label.component';

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

  let queries: string[] = [];

  async function render(wide: boolean) {
    queries = [];
    // A plain function, as in test-setup: a vi.fn would lose its implementation to another spec's restoreAllMocks.
    window.matchMedia = (query: string) => {
      queries.push(query);
      return { ...matchMedia(query), matches: wide };
    };
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const tooltip = fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip);
    const root = fixture.nativeElement as HTMLElement;
    return { fixture, tooltip, root, name: root.querySelector('[data-tab-name]')! };
  }

  it('switches at md, the width at which the page tabs and their names fit on one row', async () => {
    await render(true);
    expect(queries.filter(query => query.includes('width'))).toEqual(['(min-width: 768px)']);
    // The tab group shares out its width exactly where the names hide, or named tabs would be squeezed.
    for (const cls of COMPACT_PAGE_TABS.split(' ')) expect(cls).toMatch(/^max-md:/);
  });

  it('below md shows the icon alone, keeping the name as the accessible text and offering it as the tooltip', async () => {
    const { root, name, tooltip } = await render(false);
    expect(root.querySelector('mat-icon')?.getAttribute('aria-hidden')).toBe('true');
    expect(name.textContent?.trim()).toBe('Correlations');
    expect(name.classList).toContain('max-md:sr-only');
    expect(name.classList).not.toContain('sr-only');
    expect(tooltip.message).toBe('Correlations');
    expect(tooltip.disabled).toBe(false);
    // A phone has no hover: Material's long-press must stay on for the tooltip to be reachable.
    expect(tooltip.touchGestures).not.toBe('off');
  });

  it('from md up shows the name and no tooltip', async () => {
    const { name, tooltip } = await render(true);
    expect(name.classList).not.toContain('sr-only');
    expect(tooltip.disabled).toBe(true);
  });

  it('from md up shows a hint in place of the visible name', async () => {
    const { fixture, tooltip } = await render(true);
    fixture.componentInstance.hint.set('Locked until 10 more comparisons');
    fixture.detectChanges();
    expect(tooltip.message).toBe('Locked until 10 more comparisons');
    expect(tooltip.disabled).toBe(false);
    // Material sets pointer-events: none on a disabled tab; the label opts back in so the hint can show.
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-tab-label]')!.classList).toContain('pointer-events-auto');
  });

  it('below md names the tab above its hint, since the icon is all that shows', async () => {
    const { fixture, tooltip } = await render(false);
    fixture.componentInstance.hint.set('Locked until 10 more comparisons');
    fixture.detectChanges();
    expect(tooltip.message).toBe('Correlations\nLocked until 10 more comparisons');
    expect(tooltip.tooltipClass).toBe('whitespace-pre-line');
    expect(tooltip.disabled).toBe(false);
  });
});
