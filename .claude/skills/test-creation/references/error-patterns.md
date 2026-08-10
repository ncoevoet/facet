# Test Error Patterns and Fixes

Detailed explanations and fixes for common Angular test errors in the Facet project.

## Contents

- [NG0101: Recursive ApplicationRef.tick](#ng0101-recursive-applicationreftick)
- [TS2345: Callback Signature Mismatch](#ts2345-callback-signature-mismatch)
- [NullInjectorError: No provider for X](#nullinjectorerror-no-provider-for-x)
- [firstValueFrom hangs / test times out](#firstvaluefrom-hangs-test-times-out)
- [NG0303: Can't bind since it isn't a known input](#ng0303-cant-bind-since-it-isnt-a-known-input)
- [TS6133: Signal Tracking Warning](#ts6133-signal-tracking-warning)
- [Error-Fix Reference Table](#error-fix-reference-table)

## NG0101: Recursive ApplicationRef.tick

**Root cause**: `TestBed.flushEffects()` calls `ApplicationRef.tick()`. Inside `fakeAsync`, this enters zone stability tracking, which emits `onStable`, triggering another `tick()` -- recursive tick = NG0101.

```typescript
// WRONG: fakeAsync + flushEffects
it('should work', fakeAsync(() => {
  TestBed.flushEffects(); // NG0101!
}));

// CORRECT: synchronous test, no fakeAsync
it('should work', () => {
  fixture.detectChanges();
  TestBed.flushEffects();
});
```

**Key rules for effect-triggering tests:**
- Mock HTTP services with synchronous `of()` -- NO `delay(0)`
- Use `fixture.detectChanges()` THEN `TestBed.flushEffects()` -- NO `fakeAsync`/`tick`
- `fakeAsync` is fine for non-effect tests (e.g., debounced form inputs)

## TS2345: Callback Signature Mismatch

```typescript
// WRONG: arrow fn returns Subscription implicitly
effect(() => this.api.get('/photos').subscribe(d => this.data.set(d)));

// CORRECT: explicit void block body
effect(() => { this.api.get('/photos').subscribe(d => this.data.set(d)); });
```

**Detection**: Search for `=> .*\.subscribe(` to find violations.

## NullInjectorError: No provider for X

Create mock in TestBed providers:

```typescript
providers: [
  { provide: ApiService, useValue: mockApiService },
  { provide: I18nService, useValue: mockI18nService },
  { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
  { provide: ActivatedRoute, useValue: { snapshot: { params: {} }, queryParams: of({}) } },
]
```

## firstValueFrom hangs / test times out

The observable mock never completed:

```typescript
// WRONG: Subject never completes
mockApi.get.and.returnValue(new Subject());

// CORRECT: of() emits and completes synchronously
mockApi.get.and.returnValue(of(mockData));
```

## NG0303: Can't bind since it isn't a known input

The input name doesn't match:

```typescript
// Check the component to find the exact input name
readonly photo = input.required<Photo>(); // name is 'photo'

// CORRECT
fixture.componentRef.setInput('photo', mockPhoto);

// WRONG
fixture.componentRef.setInput('photoInput', mockPhoto); // no 'Input' suffix in this project
```

## TS6133: Signal Tracking Warning

```typescript
// Effect tracks signal but value is unused -- expected behavior
effect(() => {
  void this.personId(); // Use void to indicate intentional tracking
  this.reloadData();
});
```

## Error-Fix Reference Table

| Error | Root Cause | Fix |
|-------|-----------|-----|
| `NG0101: ApplicationRef.tick is called recursively` | `fakeAsync` + `TestBed.flushEffects()` | Remove `fakeAsync`, use `of()` mocks + `detectChanges()` + `flushEffects()` |
| `TS2345: Argument of type '() => Subscription'` | Callback returns Subscription instead of void | Use block body `{ ... }` |
| `NG0303: Can't set value` | Wrong input property name | Use exact property name from component |
| Test hangs / timeout | Observable never completes (firstValueFrom) | Use `of()` for synchronous mock data, not `new Subject()` |
| `NullInjectorError: No provider for X` | Service not mocked in TestBed | Add `{ provide: ServiceName, useValue: mockService }` to providers |
| Mock returns wrong values across tests | Spy shared across tests | Reset spies in `beforeEach` or use `.and.returnValue()` per test |
| Empty arrays/null values | Effects not executing | `TestBed.flushEffects()` |
| Observable timing issues | Lifecycle not managed | `fakeAsync` + `tick()` |
| `firstValueFrom` hangs | Observable never completes | Mock with `of()` which auto-completes |
