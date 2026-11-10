import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { SelectTriggerLabelComponent } from './select-trigger-label.component';

@Component({
  imports: [SelectTriggerLabelComponent],
  template: `
    <app-select-trigger-label [icon]="{ text: 'event', classes: 'text-red-500' }">Date</app-select-trigger-label>
    <app-select-trigger-label [icon]="{ text: 'sort', classes: '' }" iconClass="!mr-2">Other</app-select-trigger-label>
  `,
})
class HostComponent {}

describe('SelectTriggerLabelComponent', () => {
  it('renders the icon text, its classes and the projected label', () => {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const [first, second] = Array.from(fixture.nativeElement.querySelectorAll('app-select-trigger-label')) as HTMLElement[];
    const icon = first.querySelector('mat-icon') as HTMLElement;
    expect(icon.textContent?.trim()).toBe('event');
    expect(icon.classList.contains('text-red-500')).toBe(true);
    expect(icon.classList.contains('shrink-0')).toBe(true);
    expect(first.querySelector('span.truncate')?.textContent?.trim()).toBe('Date');
    expect((second.querySelector('mat-icon') as HTMLElement).classList.contains('!mr-2')).toBe(true);
    expect((second.querySelector('mat-icon') as HTMLElement).classList.contains('shrink-0')).toBe(false);
  });
});
