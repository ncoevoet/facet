---
name: test-creation
description: Create comprehensive test suites and fix failing tests for Angular 20 zoneless signal components. Use when creating tests, fixing test failures, improving coverage, handling TS2345 errors, testing signal inputs/outputs, testing effects and computed signals, testing services with firstValueFrom, or testing standalone components with inline templates. Do NOT use for E2E/Playwright tests, Python backend tests, test infrastructure/CI setup, or Karma configuration changes.
triggers:
  - "create tests"
  - "write tests"
  - "add tests"
  - "fix test"
  - "failing test"
  - "test failure"
  - "NG0101"  # For NG0101 in tests (fakeAsync/flushEffects); use effect-safety-validator for runtime NG0101
  - "TS2345"
  - "fakeAsync"
  - "flushEffects"
  - "test times out"
  - "firstValueFrom hangs"
  - "improve coverage"
  - "test signal"
  - "test component"
  - "test service"
  - "test pipe"
  - "NullInjectorError"
  - "spec file"
  - "Karma"
  - "Jasmine"
negative_triggers:
  - "Playwright"
  - "E2E"
  - "end-to-end"
  - "pytest"
  - "Python test"
  - "backend test"
  - "Karma config"
  - "karma.conf"
  - "CI setup"
---

# Test Creation and Fixing Skill

Expert guidance for creating signal-based component tests and fixing test failures in the Facet Angular 20 project using Karma, Jasmine, and TestBed.

## Core Testing Principles

### 1. Signal Testing Basics
- Use `TestBed.flushEffects()` after signal changes to flush effects
- Use `fixture.componentRef.setInput(name, value)` to set input signal values
- Subscribe directly to output signals: `component.outputSignal.subscribe(spy)`
- Test computed signals by changing dependent signals and checking results

### 2. Test Structure Pattern

```typescript
describe('ComponentName', () => {
  let component: ComponentName;
  let fixture: ComponentFixture<ComponentName>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ComponentName, /* standalone dependencies */],
      providers: [/* mocked services */]
    }).compileComponents();

    fixture = TestBed.createComponent(ComponentName);
    component = fixture.componentInstance;
    fixture.detectChanges(); // Initial change detection + effect scheduling
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
```

**Important**: All components are standalone with inline templates. Import the component directly in `imports`, not in `declarations`.

### 3. Common Test Patterns

#### Testing Signal Inputs
```typescript
it('should update computed value when input changes', () => {
  fixture.componentRef.setInput('photo', mockPhoto);
  fixture.detectChanges();
  TestBed.flushEffects();

  expect(component.thumbnailUrl()).toContain(mockPhoto.path);
});
```

#### Testing Output Signals
```typescript
it('should emit when photo clicked', () => {
  const spy = jasmine.createSpy('photoClicked');
  component.photoClicked.subscribe(spy);

  component.onClick();

  expect(spy).toHaveBeenCalledWith(expectedPhoto);
});
```

#### Testing Computed Signals
```typescript
it('should compute filtered count from photos input', () => {
  fixture.componentRef.setInput('photos', [photo1, photo2, photo3]);
  fixture.detectChanges();
  TestBed.flushEffects();

  expect(component['filteredPhotos']().length).toBe(3);
});
```

#### Testing Effects
```typescript
it('should load data when query input changes', () => {
  mockApi.get.and.returnValue(of({ photos: [mockPhoto] }));

  fixture.componentRef.setInput('query', 'landscape');
  fixture.detectChanges();
  TestBed.flushEffects();

  expect(component['data']()).toEqual([mockPhoto]);
});
```

#### Testing Effect Cleanup with onCleanup
```typescript
it('should cleanup subscriptions when effect re-runs', () => {
  fixture.componentRef.setInput('personId', 1);
  fixture.detectChanges();
  TestBed.flushEffects();
  expect(mockApi.get).toHaveBeenCalledTimes(1);

  fixture.componentRef.setInput('personId', 2);
  fixture.detectChanges();
  TestBed.flushEffects();
  expect(mockApi.get).toHaveBeenCalledTimes(2);
});

it('should cleanup on destroy', () => {
  fixture.componentRef.setInput('personId', 1);
  fixture.detectChanges();
  TestBed.flushEffects();
  fixture.destroy(); // onCleanup called
});
```

#### Testing ViewChild Signals
```typescript
it('should access child element', () => {
  fixture.detectChanges();
  TestBed.flushEffects();
  expect(component.scrollContainer()).toBeDefined();
});
```

## Synchronous vs Asynchronous Decision Matrix

| Scenario | Use Sync | Use Async | Example |
|----------|----------|-----------|---------|
| Signal value inspection | Yes | No | `component.photos()` |
| Pure method testing | Yes | No | `service.thumbnailUrl(path)` |
| Service injection checks | Yes | No | Verify service exists in component |
| Constructor effect testing | Yes | No | Direct signal updates via effects |
| Debounced form input | No | Yes | Form valueChanges with debounceTime |
| Timer-based operations | No | Yes | setTimeout, interval, delay operators |
| firstValueFrom in async methods | No | Yes | Store methods returning Promise |

**Key**: Prefer synchronous -- faster, no timing fragility, cleaner code.

## Testing Services with firstValueFrom

Services in this project use `firstValueFrom()` to convert HTTP observables to promises:

```typescript
describe('GalleryStore', () => {
  let store: GalleryStore;
  let mockApi: jasmine.SpyObj<ApiService>;

  beforeEach(() => {
    mockApi = jasmine.createSpyObj('ApiService', ['get', 'post', 'thumbnailUrl']);
    mockApi.get.and.returnValue(of({
      photos: [mockPhoto],
      total: 1,
      page: 1,
      per_page: 64,
      has_more: false,
    }));

    TestBed.configureTestingModule({
      providers: [
        GalleryStore,
        { provide: ApiService, useValue: mockApi }
      ]
    });
    store = TestBed.inject(GalleryStore);
  });

  it('should load photos via firstValueFrom', async () => {
    await store.loadPhotos({ sort: 'aggregate' });

    expect(mockApi.get).toHaveBeenCalledWith('/photos', jasmine.objectContaining({ sort: 'aggregate' }));
    expect(store.photos().length).toBe(1);
  });

  it('should handle errors gracefully', async () => {
    mockApi.get.and.returnValue(throwError(() => new Error('Network error')));

    await store.loadPhotos({ sort: 'aggregate' }).catch(() => {});

    expect(store.loading()).toBe(false);
  });

  it('should set loading state', async () => {
    const deferred = new Subject<PhotosResponse>();
    mockApi.get.and.returnValue(deferred.asObservable());

    const promise = store.loadPhotos({ sort: 'aggregate' });
    expect(store.loading()).toBe(true);

    deferred.next({ photos: [], total: 0, page: 1, per_page: 64, has_more: false });
    deferred.complete();
    await promise;
    expect(store.loading()).toBe(false);
  });
});
```

**Critical**: Mocked observables for `firstValueFrom()` MUST complete. Always use `of()` (auto-completes). Never use `new Subject()` without calling `.complete()` -- `firstValueFrom` will hang forever.

## Mocking Services

For complete mock patterns (ApiService, I18nService, AuthService, HttpClient, TranslatePipe), see `references/mocking-patterns.md`.

Quick reference:
```typescript
const mockApiService = jasmine.createSpyObj('ApiService', ['get', 'post', 'thumbnailUrl']);
mockApiService.get.and.returnValue(of({}));

const mockI18nService = {
  t: jasmine.createSpy('t').and.callFake((key: string) => `translated:${key}`),
  locale: jasmine.createSpy('locale').and.returnValue('en'),
  isLoaded: jasmine.createSpy('isLoaded').and.returnValue(true),
};
```

## Testing Standalone Components with Material

Most components import Angular Material modules. Add them to TestBed:

```typescript
await TestBed.configureTestingModule({
  imports: [
    MyComponent,       // The component under test (standalone)
    NoopAnimationsModule,  // Required for Material components
  ],
  providers: [
    { provide: ApiService, useValue: mockApiService },
    { provide: I18nService, useValue: mockI18nService },
  ]
}).compileComponents();
```

**Note**: Since components are standalone with their own `imports` array, Material modules imported by the component are resolved automatically. You only need `NoopAnimationsModule` in TestBed to prevent animation errors.

## Using fakeAsync for Non-Effect Tests

`fakeAsync` is fine when NOT combined with `flushEffects`:

```typescript
it('should handle debounced search', fakeAsync(() => {
  component.onSearchInput('test');
  tick(300); // Wait for debounce
  expect(mockApi.get).toHaveBeenCalled();
}));
```

**Common pitfall**:

```typescript
// WRONG: Testing async behavior with synchronous test
it('should handle form changes', () => {
  component.searchControl.setValue('test');
  expect(mockApi.get).toHaveBeenCalled(); // API call happens after debounce!
});

// CORRECT: Use fakeAsync for debounced operations
it('should handle form changes', fakeAsync(() => {
  component.searchControl.setValue('test');
  tick(300); // Wait for debounce
  expect(mockApi.get).toHaveBeenCalled();
}));
```

## Test Helper Functions

For mock data factories and helper patterns, see `references/mocking-patterns.md`.

## Handling Common Test Errors

For detailed error explanations, code examples, and fixes, see `references/error-patterns.md`.

Quick rules:
- **NG0101**: Never combine `fakeAsync` with `TestBed.flushEffects()`
- **firstValueFrom hangs**: Always use `of()` (auto-completes), never raw `Subject`
- **NullInjectorError**: Add `{ provide: ServiceName, useValue: mockService }` to providers
- **TS2345**: Use block body `{ ... }` in effect callbacks, not arrow expression

## Test File Creation Checklist

When creating a comprehensive test suite:

- Create describe block for component/service
- Setup beforeEach with TestBed configuration
- Add 'should create' test
- Test each input signal with `setInput()` and `flushEffects()`
- Test each output signal with subscription spies
- Test computed signals by changing dependencies
- Test effects that call services (mock with `of()`)
- Test async methods that use `firstValueFrom()` (use `async/await`)
- Test error handling paths
- Verify all tests pass: `npx ng test --watch=false` from `client/` dir

## Quick Execution Commands

```bash
# Run all tests (from client/ directory)
npx ng test

# Run once (CI mode)
npx ng test --watch=false

# Run with coverage
npx ng test --code-coverage

# Build check (no type errors)
npx ng build
```

## Verify Test Quality

After fixing or creating tests, verify:

1. **Compilation**: `npx ng build` (no type errors)
2. **Tests Pass**: `npx ng test --watch=false`
3. **Coverage**: All public methods tested
4. **No Timeouts**: Tests complete without hangs (check firstValueFrom mocks)
5. **Proper Cleanup**: Effects properly cleaned up, no memory leaks

## Examples

**User says**: "Create tests for GalleryComponent"
1. Read `gallery.component.ts` -- identify inputs, outputs, effects, injected services
2. Create spec with `TestBed.configureTestingModule`, mock all injected services with `of()` returns
3. Add `NoopAnimationsModule` for Material components
4. Test signal state with `fixture.componentRef.setInput()` + `TestBed.flushEffects()`
5. Test outputs with subscription spies
6. Test async store methods with `async/await`
7. Run: `npx ng test --watch=false` from `client/`
8. Fix any failures, verify coverage

**User says**: "Fix failing test -- NG0101 recursive tick error"
1. Identify the test using `fakeAsync` + `TestBed.flushEffects()` combination
2. Remove `fakeAsync`/`tick` wrapper
3. Use synchronous `of()` mocks instead of async patterns
4. Keep `fixture.detectChanges()` + `TestBed.flushEffects()` (no fakeAsync)
5. Re-run test to verify fix

**User says**: "Test times out -- firstValueFrom hangs"
1. Check mock: is it returning `of()` or a `Subject`?
2. Replace `new Subject()` or `new BehaviorSubject()` with `of(mockData)`
3. If testing loading states, use `Subject` but call `.next()` and `.complete()` in the test
4. Re-run test to verify fix

**User says**: "Create tests for TranslatePipe"
1. Set up TestBed with `TranslatePipe` and mocked `I18nService`
2. Test key translation, variable passing, missing keys
3. No fakeAsync needed -- pipe is synchronous
4. Verify with `npx ng test --watch=false`

## Critical Rules

- **NEVER** combine `fakeAsync` with `TestBed.flushEffects()` -- causes NG0101
- **NEVER** import `zone.js` in test files (already in polyfills via angular.json)
- **NEVER** call `TestBed.initTestEnvironment()` -- already configured globally
- **Framework**: Karma + Jasmine (not Jest)
- **Spy syntax**: Use `jasmine.createSpy()` and `jasmine.createSpyObj()` (not `jest.fn()`)
- **Mocking**: Use `jasmine.createSpyObj('Name', ['method1', 'method2'])` for service mocks
- **Assertions**: Use `expect().toBe()`, `toEqual()`, `toHaveBeenCalledWith()` (Jasmine matchers)

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `NG0101: ApplicationRef.tick is called recursively` | `fakeAsync` + `TestBed.flushEffects()` | Remove `fakeAsync`, use `of()` mocks + `detectChanges()` + `flushEffects()` |
| `TS2345: Argument of type '() => Subscription'` | Callback returns Subscription instead of void | Add explicit `void` return or wrap in braces: `() => { sub(); }` |
| Test hangs / timeout | Observable never completes (firstValueFrom) | Use `of()` for synchronous mock data, not `new Subject()` |
| `NullInjectorError: No provider for X` | Service not mocked in TestBed | Add `{ provide: ServiceName, useValue: mockService }` to providers |
| Mock returns wrong values across tests | Spy shared across tests | Reset spies in `beforeEach` or use `.and.returnValue()` per test |
| `NG0303: Can't bind` | Wrong input name in setInput | Use exact property name (no suffixes in this project) |

## See Also

- **signal-patterns** — Signal/computed/effect patterns, mutation detection, parent-child communication
- **effect-safety-validator** — Detect unsafe effect patterns (infinite loops, NG0101, Angular 20 breaking changes)
