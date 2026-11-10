import { DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, Subject, takeUntil } from 'rxjs';

export interface LatestRequestHandle {
  isCurrent(): boolean;
  bind<T>(source: Observable<T>): Observable<T>;
}

export class LatestRequest {
  private id = 0;
  private readonly superseded = new Subject<void>();

  constructor(private readonly destroyRef: DestroyRef) {}

  cancel(): void {
    this.id++;
    this.superseded.next();
  }

  begin(): LatestRequestHandle {
    this.cancel();
    const id = this.id;
    return {
      isCurrent: () => !this.destroyRef.destroyed && id === this.id,
      bind: <T>(source: Observable<T>) => source.pipe(
        takeUntil(this.superseded), takeUntilDestroyed(this.destroyRef),
      ),
    };
  }
}
