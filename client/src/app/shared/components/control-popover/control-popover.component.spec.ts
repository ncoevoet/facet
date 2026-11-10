import { OverlayContainer } from '@angular/cdk/overlay';
import { getDebugNode } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { I18nService } from '../../../core/services/i18n.service';
import { ControlPopoverComponent } from './control-popover.component';

describe('ControlPopoverComponent', () => {
  function rect(left: number, width: number): DOMRect {
    return { left, width, right: left + width, top: 0, bottom: 20, height: 20, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
  }

  async function open(fill: boolean, withRail: boolean | string, iconOnly = false) {
    TestBed.configureTestingModule({
      imports: [ControlPopoverComponent],
      providers: [{ provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } }],
    });
    const rail = document.createElement('div');
    if (withRail) rail.setAttribute(withRail === true ? 'data-details-rail' : withRail, '');
    document.body.appendChild(rail);
    const fixture = TestBed.createComponent(ControlPopoverComponent);
    rail.appendChild(fixture.nativeElement);
    fixture.componentRef.setInput('label', 'About these measurements');
    fixture.componentRef.setInput('fill', fill);
    fixture.componentRef.setInput('iconOnly', iconOnly);
    fixture.detectChanges();
    const trigger = (fixture.nativeElement as HTMLElement).querySelector('button')!;
    // jsdom has no layout: a 400 px rail whose trigger sits 8 px inside it.
    rail.getBoundingClientRect = () => rect(100, 400);
    trigger.getBoundingClientRect = () => rect(108, 384);
    trigger.click();
    fixture.detectChanges();
    await fixture.whenStable();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, rail, trigger, overlay, pane: overlay.querySelector<HTMLElement>('.cdk-overlay-pane')!, panel: overlay.querySelector<HTMLElement>('[role="dialog"]')! };
  }

  it('fills the rail minus 8 px a side when asked to, and stretches the trigger', async () => {
    const { fixture, rail, trigger, pane, panel } = await open(true, true);
    expect(trigger.className).toContain('w-full');
    expect(trigger.className).toContain('justify-start');
    expect(pane.style.width).toBe('384px');
    expect(panel.className).toContain('w-full');
    expect(panel.className).not.toContain('w-80');
    fixture.destroy();
    rail.remove();
  });

  it('keeps the 320 px panel and the centred inline trigger by default', async () => {
    const { fixture, rail, trigger, pane, panel } = await open(false, true);
    expect(trigger.className).not.toContain('w-full');
    expect(pane.style.width).toBe('');
    expect(panel.className).toContain('w-80');
    expect(panel.className).not.toContain('w-full');
    fixture.destroy();
    rail.remove();
  });

  it('falls back to the trigger width off the rail', async () => {
    const { fixture, rail, pane } = await open(true, false);
    expect(pane.style.width).toBe('368px');
    fixture.destroy();
    rail.remove();
  });

  it('shows only the icon when asked to, naming itself through its aria-label and tooltip', async () => {
    const { fixture, rail, trigger } = await open(false, true, true);
    expect(trigger.textContent!.trim()).toBe('tune');
    expect(trigger.getAttribute('aria-label')).toBe('About these measurements');
    const tooltip = fixture.debugElement.query(By.css('button')).injector.get(MatTooltip);
    expect(tooltip.message).toBe('About these measurements');
    expect(tooltip.disabled).toBe(false);
    expect(trigger.className).toContain('min-w-7');
    fixture.destroy();
    rail.remove();
  });

  it('keeps an icon-only trigger compact but still opens a filled panel at the photo inspector width', async () => {
    const { fixture, rail, trigger, pane, panel } = await open(true, 'data-photo-inspector', true);
    expect(trigger.className).not.toContain('w-full');
    expect(pane.style.width).toBe('384px');
    expect(panel.className).toContain('w-full');
    fixture.destroy();
    rail.remove();
  });

  it('opens an icon-only filled panel at the default width when no rail surrounds it', async () => {
    const { fixture, rail, pane, panel } = await open(true, false, true);
    expect(pane.style.width).toBe('');
    expect(panel.className).toContain('w-80');
    fixture.destroy();
    rail.remove();
  });

  it('names its close button in a tooltip', async () => {
    const { fixture, rail, panel } = await open(false, true);
    const close = panel.querySelector('header button')!;
    expect(getDebugNode(close)!.injector.get(MatTooltip).message).toBe('dialog.close');
    fixture.destroy();
    rail.remove();
  });

  it('gives a labelled trigger no tooltip', async () => {
    const { fixture, rail } = await open(false, true);
    expect(fixture.debugElement.query(By.css('button')).injector.get(MatTooltip).disabled).toBe(true);
    fixture.destroy();
    rail.remove();
  });
});
