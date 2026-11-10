import { DestroyRef, Injectable, effect, inject } from '@angular/core';
import { Location } from '@angular/common';
import { NavigationEnd, NavigationStart, Router } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

export interface GalleryHistoryPosition {
  owner: string;
  url: string;
  scroll: number;
  path: string | null;
  page: number;
  anchor: { offset: number; width: number; height: number } | null;
}

/** Bounded, tab-local positions keyed by the Router's existing history ids.
 * No photo paths or high-frequency writes are added to browser history. */
@Injectable({ providedIn: 'root' })
export class GalleryVisitPositions {
  private readonly location = inject(Location);
  private readonly positions = new Map<number, GalleryHistoryPosition>();
  private restoration: { navigation: number; entry: number | undefined } | null = null;
  constructor() {
    const auth = inject(AuthService);
    effect(() => {
      const owner = auth.identity();
      for (const [id, value] of this.positions) if (value.owner !== owner) this.positions.delete(id);
    });
    inject(Router).events.pipe(takeUntilDestroyed(inject(DestroyRef))).subscribe(event => {
      if (event instanceof NavigationStart) {
        this.restoration = { navigation: event.id, entry: event.restoredState?.navigationId };
      } else if (event instanceof NavigationEnd) {
        // Kept galleries are reattached without constructing a component. Their
        // entry still gets a new Router id, even if no input follows the return.
        this.restore(auth.identity(), event.urlAfterRedirects, event.id);
      }
    });
  }
  remember(position: GalleryHistoryPosition): void {
    const entry = (this.location.getState() as { navigationId?: number } | null)?.navigationId;
    if (!Number.isSafeInteger(entry)) return;
    // Changing accounts discards private positions, including a rapid account
    // switch before a reactive cleanup would otherwise run.
    for (const [id, value] of this.positions) if (value.owner !== position.owner) this.positions.delete(id);
    this.positions.delete(entry!);
    this.positions.set(entry!, position);
    while (this.positions.size > 32) this.positions.delete(this.positions.keys().next().value!);
  }
  restore(owner: string, url: string, navigation: number): GalleryHistoryPosition | null {
    if (this.restoration?.navigation !== navigation || this.restoration.entry === undefined) return null;
    const position = this.positions.get(this.restoration.entry);
    if (!position || position.owner !== owner || position.url !== url) return null;
    // Angular gives a restored entry a new navigation id. Keep its position
    // under that id even when the user leaves again without scrolling.
    this.remember(position);
    return position;
  }
}
