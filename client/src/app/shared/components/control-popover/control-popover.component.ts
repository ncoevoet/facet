import { ChangeDetectionStrategy, Component, inject, input, output, signal, TemplateRef } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { CdkConnectedOverlay, CdkOverlayOrigin, ConnectedPosition } from '@angular/cdk/overlay';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import { MatIconModule } from '@angular/material/icon';
import { I18N } from '../../../core/i18n/keys';
import { TranslatePipe } from '../../pipes/translate.pipe';

let nextPopover = 0;

/** A scroll-contained settings/help panel that never changes its owner's layout. */
@Component({
  selector: 'app-control-popover',
  imports: [CdkConnectedOverlay, CdkOverlayOrigin, CdkTrapFocus, MatIconModule, TranslatePipe, NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'contents' },
  template: `
    <button #trigger type="button" cdkOverlayOrigin #origin="cdkOverlayOrigin"
            class="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-2 rounded px-2 text-sm hover:bg-[var(--mat-sys-surface-container-high)] focus-visible:outline-2 focus-visible:outline-[var(--mat-sys-primary)]"
            [class.bg-[var(--mat-sys-secondary-container)]]="open()"
            [attr.aria-label]="label()" [attr.title]="hint() || null" aria-haspopup="dialog" [attr.aria-expanded]="open()"
            [attr.aria-controls]="open() ? panelId : null" (click)="toggle()">
      <mat-icon aria-hidden="true" class="!h-5 !w-5 !text-xl">{{ icon() }}</mat-icon>
      <span [class]="compact() ? 'hidden @min-[480px]:inline' : ''">{{ label() }}</span>
      @if (disclosure()) { <mat-icon aria-hidden="true" class="!hidden !h-4 !w-4 !text-base @min-[960px]:!inline-flex" [class.rotate-180]="open()">expand_more</mat-icon> }
    </button>
    <ng-template cdkConnectedOverlay [cdkConnectedOverlayOrigin]="origin" [cdkConnectedOverlayOpen]="open()"
                 [cdkConnectedOverlayPush]="true" [cdkConnectedOverlayPositions]="positions" [cdkConnectedOverlayHasBackdrop]="true"
                 cdkConnectedOverlayBackdropClass="cdk-overlay-transparent-backdrop" [cdkConnectedOverlayViewportMargin]="8"
                 (backdropClick)="open.set(false)" (detach)="onDetached()">
      <section [id]="panelId" tabindex="-1" role="dialog" aria-modal="true" [attr.aria-label]="label()"
               cdkTrapFocus [cdkTrapFocusAutoCapture]="true" (keydown)="onKeydown($event)"
               class="flex max-h-[min(75dvh,44rem)] w-80 max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-lg border border-[var(--mat-sys-outline-variant)] bg-[var(--mat-sys-surface-container)] text-[var(--mat-sys-on-surface)] shadow-xl">
        <header class="flex shrink-0 items-center gap-2 border-b border-[var(--mat-sys-outline-variant)] px-3 py-1">
          <span class="min-w-0 flex-1 text-sm font-medium">{{ label() }}</span>
          <button type="button" cdkFocusInitial class="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded hover:bg-[var(--mat-sys-surface-container-high)]"
                  [attr.aria-label]="I18N.dialog.close | translate" (click)="open.set(false)"><mat-icon aria-hidden="true">close</mat-icon></button>
        </header>
        <div class="min-h-0 overflow-y-auto p-3"><ng-container [ngTemplateOutlet]="content()" /></div>
      </section>
    </ng-template>
  `,
})
export class ControlPopoverComponent {
  protected readonly I18N = I18N;
  readonly label = input.required<string>();
  readonly icon = input('tune');
  readonly compact = input(false);
  readonly disclosure = input(false);
  readonly hint = input('');
  readonly content = input<TemplateRef<unknown> | null>(null);
  readonly open = signal(false);
  readonly opened = output<void>();
  readonly closed = output<void>();
  /** Stay open when a navigation only rewrites the query string, e.g. a filter this popover changed. */
  readonly keepOnQueryChange = input(false);
  protected onDetached(): void {
    this.open.set(false);
    this.closed.emit();
  }
  protected toggle(): void {
    this.open.update(value => !value);
    if (this.open()) this.opened.emit();
  }
  constructor() {
    const router = inject(Router, { optional: true });
    router?.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (!(event instanceof NavigationStart)) return;
      if (this.keepOnQueryChange() && event.url.split(/[?#]/)[0] === router.url.split(/[?#]/)[0]) return;
      this.open.set(false);
    });
  }
  protected readonly panelId = `facet-control-popover-${++nextPopover}`;
  protected readonly positions: ConnectedPosition[] = [
    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
    { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
  ];
  protected onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    event.preventDefault();
    event.stopPropagation();
    this.open.set(false);
  }
}
