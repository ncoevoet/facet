import { Component, viewChild } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { InfiniteScrollDirective } from './infinite-scroll.directive';

/** Captured IntersectionObserver instances and their callbacks. */
let observerInstances: {
  callback: IntersectionObserverCallback;
  options: IntersectionObserverInit | undefined;
  observe: jest.Mock;
  unobserve: jest.Mock;
  disconnect: jest.Mock;
}[];

beforeEach(() => {
  observerInstances = [];

   
  (globalThis as any).IntersectionObserver = jest.fn((callback: IntersectionObserverCallback, options?: IntersectionObserverInit) => {
    const instance = {
      callback,
      options,
      observe: jest.fn(),
      unobserve: jest.fn(),
      disconnect: jest.fn(),
    };
    observerInstances.push(instance);
    return instance;
  });
});

@Component({
  selector: 'app-test-host',
  standalone: true,
  imports: [InfiniteScrollDirective],
  template: `
    <main>
      <div appInfiniteScroll (scrollReached)="reached = true"></div>
    </main>
  `,
})
class TestHostComponent {
  reached = false;
  readonly directive = viewChild(InfiniteScrollDirective);
}

@Component({
  selector: 'app-test-custom-root',
  standalone: true,
  imports: [InfiniteScrollDirective],
  template: `
    <section class="scroll-area">
      <div appInfiniteScroll scrollRoot=".scroll-area" (scrollReached)="reached = true"></div>
    </section>
  `,
})
class TestHostCustomRootComponent {
  reached = false;
}

describe('InfiniteScrollDirective', () => {
  function createHost<T>(component: new (...args: unknown[]) => T): T {
    TestBed.configureTestingModule({ imports: [component] });
    const fixture = TestBed.createComponent(component);
    fixture.detectChanges();
    // Flush afterNextRender
    TestBed.flushEffects();
    return fixture.componentInstance;
  }

  it('should create the directive', () => {
    const host = createHost(TestHostComponent);
    expect(host.directive()).toBeTruthy();
  });

  it('should create an IntersectionObserver on render', () => {
    createHost(TestHostComponent);
    expect(observerInstances).toHaveLength(1);
    expect(observerInstances[0].observe).toHaveBeenCalledTimes(1);
  });

  it('should use the closest "main" element as root by default', () => {
    createHost(TestHostComponent);
    const instance = observerInstances[0];
    // el.closest('main') should resolve to the <main> ancestor
    expect(instance.options?.root).toBeInstanceOf(HTMLElement);
    expect((instance.options?.root as HTMLElement).tagName).toBe('MAIN');
  });

  it('should use a custom scrollRoot when provided', () => {
    createHost(TestHostCustomRootComponent);
    const instance = observerInstances[0];
    expect(instance.options?.root).toBeInstanceOf(HTMLElement);
    expect((instance.options?.root as HTMLElement).tagName).toBe('SECTION');
  });

  it('should set rootMargin to 200px', () => {
    createHost(TestHostComponent);
    expect(observerInstances[0].options?.rootMargin).toBe('200px');
  });

  it('should emit scrollReached when entry is intersecting', () => {
    const host = createHost(TestHostComponent);
    expect(host.reached).toBe(false);

    const instance = observerInstances[0];
    // Simulate an intersecting entry
    instance.callback(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      instance as unknown as IntersectionObserver,
    );

    expect(host.reached).toBe(true);
  });

  it('should NOT emit scrollReached when entry is not intersecting', () => {
    const host = createHost(TestHostComponent);

    const instance = observerInstances[0];
    instance.callback(
      [{ isIntersecting: false } as IntersectionObserverEntry],
      instance as unknown as IntersectionObserver,
    );

    expect(host.reached).toBe(false);
  });

  it('should disconnect the observer on destroy', () => {
    TestBed.configureTestingModule({ imports: [TestHostComponent] });
    const fixture = TestBed.createComponent(TestHostComponent);
    fixture.detectChanges();
    TestBed.flushEffects();

    const instance = observerInstances[0];
    expect(instance.disconnect).not.toHaveBeenCalled();

    fixture.destroy();

    expect(instance.disconnect).toHaveBeenCalledTimes(1);
  });

  it('should unobserve and re-observe on recheck()', () => {
    const host = createHost(TestHostComponent);
    const instance = observerInstances[0];
    const directive = host.directive()!;

    directive.recheck();

    expect(instance.unobserve).toHaveBeenCalledTimes(1);
    // observe: 1 from setup + 1 from recheck
    expect(instance.observe).toHaveBeenCalledTimes(2);
  });
});
