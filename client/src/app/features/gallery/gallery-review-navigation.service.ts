import { effect, inject, Injectable, signal } from '@angular/core';
import { AuthService } from '../../core/services/auth.service';

/** A session choice, independent of query predicates and display presets. */
@Injectable({ providedIn: 'root' })
export class GalleryReviewNavigationService {
  private readonly auth = inject(AuthService);
  private owner = this.context();
  private readonly choice = signal(false);
  readonly enabled = this.choice.asReadonly();
  private revision = 0;

  constructor() {
    effect(() => { this.syncOwner(); });
  }

  private context(): string | null {
    return this.auth.status() && this.auth.isEdition()
      ? JSON.stringify([this.auth.identity(), this.auth.token]) : null;
  }

  private syncOwner(): string | null {
    const owner = this.context();
    if (owner !== this.owner) {
      this.owner = owner;
      this.choice.set(false);
      this.revision++;
    }
    return owner;
  }

  setEnabled(enabled: boolean): void {
    if (!this.syncOwner()) return;
    this.choice.set(enabled);
    this.revision++;
  }

  /** Changing the policy while a write is pending cannot retroactively advance it. */
  capture(): () => boolean {
    const owner = this.syncOwner();
    const revision = this.revision;
    const enabled = this.choice();
    return () => this.syncOwner() === owner && owner !== null && enabled
      && this.choice() && revision === this.revision;
  }
}
