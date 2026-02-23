---
name: effect-safety-validator
description: Detect and fix unsafe effect patterns in Angular signals including constructor effects, form mutations, observable subscriptions in effects, and feedback loops. Use when fixing infinite loops, detecting ObjectUnsubscribedError, preventing form mutation side effects, or validating effect safety patterns. Do NOT use for general signal migration, simple component testing, or non-effect-related Angular issues.
triggers:
  - "infinite loop"
  - "effect loop"
  - "feedback loop"
  - "ObjectUnsubscribedError"
  - "NG0101"  # For runtime NG0101 errors; use test-creation for NG0101 in test context
  - "recursive tick"
  - "Maximum call stack"
  - "form patchValue"
  - "emitEvent"
  - "untracked"
  - "effect safety"
  - "subscription leak"
  - "takeUntilDestroyed"
  - "queueMicrotask"
  - "effect cleanup"
negative_triggers:
  - "create test"
  - "write test"
  - "CSS"
  - "layout"
  - "Python"
  - "backend"
  - "simple signal"
  - "input signal"
---

# Effect Safety Validator Skill

Expert guidance for identifying and fixing unsafe Angular effect patterns, preventing infinite loops, and ensuring proper effect lifecycle management.

## Critical Effect Patterns

### Subscription Cleanup in Effects
**CRITICAL**: All subscriptions in effects MUST be properly cleaned up

```typescript
// BAD: Subscription never unsubscribed
effect(() => {
  this.service.getData().subscribe(data => {
    this.$data.set(data);
  });
  // Memory leak! Subscription persists until component destroyed
});

// SAFE: Using onCleanup for proper cleanup
effect(() => {
  const subscription = this.service.getData().subscribe(data => {
    this.$data.set(data);
  });

  return () => subscription.unsubscribe();
}, { manualCleanup: true });

// BETTER: Use takeUntilDestroyed (preferred)
effect(() => {
  this.service.getData()
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe(data => this.$data.set(data));
});
```

### Form Mutations in Effects (Feedback Loop Prevention)
**CRITICAL**: Form mutations in effects MUST use `{emitEvent: false}` to prevent infinite loops

```typescript
// DANGEROUS: Feedback loop
effect(() => {
  const value = this.$selectedValue();
  // When form.patchValue emits, it triggers the effect again = infinite loop
  this.form.patchValue({ field: value });
});

// SAFE: Prevent event emission with {emitEvent: false}
effect(() => {
  const value = this.$selectedValue();
  this.form.patchValue({ field: value }, { emitEvent: false });
});
```

### Anti-Pattern: Observable in Effect
**CRITICAL**: Don't call observable-returning methods inside effects without subscription

```typescript
// DANGEROUS: Observable created but not subscribed
effect(() => {
  this.service.getData(); // Observable never executes!
});

// SAFE: Subscribe to observable
effect(() => {
  this.service.getData()
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe(data => this.$data.set(data));
});

// OR: Use toSignal (automatic subscription)
$data = toSignal(
  this.service.getData(),
  { initialValue: [] }
);
```

## Unsafe Constructor Effect Pattern
**Pattern**: Initializing data in constructor effect

```typescript
// UNSAFE: Effect in constructor
constructor() {
  effect(() => {
    this.service.getData()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(data => this.$data.set(data));
  });
}

// SAFE: Move to field initializer or ngOnInit
// Option 1: Use toSignal (automatic)
$data = toSignal(this.service.getData(), { initialValue: [] });

// Option 2: Initialize in ngOnInit
ngOnInit() {
  this.service.getData()
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe(data => this.$data.set(data));
}

// Option 3: Field initializer with manual effect
$data = signal<Data[]>([]);
private initData = effect(() => {
  this.service.getData()
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe(data => this.$data.set(data));
});
```

## Infinite Loop Patterns

### Pattern 1: Signal Mutation in Effect (Self-triggering)
```typescript
// INFINITE LOOP: Effect mutates signal it depends on
effect(() => {
  const count = this.$count(); // Depends on $count
  this.$count.set(count + 1);  // Mutates $count -> triggers effect again
});

// SAFE: Keep signals and effects separate
effect(() => {
  const count = this.$count();
  this.$displayValue.set(count * 2); // Different signal
});
```

### Pattern 2: Form Value Change Loop
```typescript
// INFINITE LOOP: Form patchValue triggers valueChanges which triggers effect
effect(() => {
  const value = this.form.get('field')?.value;
  this.$selectedValue.set(value);
});

this.form.valueChanges
  .pipe(takeUntilDestroyed(this.destroyRef))
  .subscribe(value => {
    effect(() => {
      this.form.patchValue({ ...value }); // Circular!
    });
  });

// SAFE: One-way data flow
effect(() => {
  const selected = this.$selectedValue();
  this.form.patchValue({ field: selected }, { emitEvent: false });
});
```

### Pattern 3: Array/Object Mutation Loop
```typescript
// DANGEROUS: Deep mutations in effects
effect(() => {
  const items = this.$items();
  items.forEach(item => {
    item.updated = true; // Mutates tracked array
  });
  // Change detection may trigger effect again with same array reference
});

// SAFE: Create new array with immutable update
effect(() => {
  const items = this.$items();
  const updated = items.map(item => ({ ...item, updated: true }));
  this.$processedItems.set(updated);
});
```

## Detection Checklist

For each effect, verify:

- **No self-referential mutations**: Effect depends on signal A, doesn't mutate A
- **Proper subscription cleanup**: Uses onCleanup or takeUntilDestroyed
- **Form mutations safe**: All form.patchValue() use `{emitEvent: false}`
- **Observable subscription present**: Observable-returning calls are subscribed to
- **No multiple effects mutating same signal**: Would create potential loops
- **Data flow direction clear**: Effects flow data in one direction
- **No circular dependencies**: Signal A -> Effect updates B; not B -> Effect updates A
- **Initialization pattern safe**: No heavy initialization in constructor effects

## Refactoring Unsafe Effects

### Unsafe: Constructor Effect with Service
```typescript
export class DataComponent {
  private readonly $data = signal<Data[]>([]);

  constructor(private service: DataService) {
    // UNSAFE: Effect in constructor
    effect(() => {
      this.service.getData().subscribe(data => {
        this.$data.set(data);
      });
    });
  }
}
```

### Safe: Use toSignal
```typescript
export class DataComponent {
  protected readonly $data = toSignal(
    inject(DataService).getData(),
    { initialValue: [] }
  );
}
```

### Safe: Use Field Initializer
```typescript
export class DataComponent {
  private readonly service = inject(DataService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly $data = signal<Data[]>([]);

  // Initializes after constructor completes
  private initData = effect(() => {
    this.service.getData()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(data => this.$data.set(data));
  });
}
```

## Verification and Testing

### Static Analysis
```bash
# Find effect() declarations
grep -r "effect(" --include="*.ts" client/src/app/

# Find potential subscription leaks
grep -r "\.subscribe(" --include="*.ts" client/src/app/ | grep "effect"

# Find patchValue without {emitEvent: false}
grep -r "patchValue" --include="*.ts" client/src/app/ | grep -v "emitEvent"
```

### Testing Effect Safety
```typescript
it('should not create infinite loop', () => {
  // Ensure effect completes within reasonable time
  fixture.detectChanges();
  TestBed.flushEffects();

  // If still running after flushEffects, likely infinite loop
  expect(component['$data']()).toBeDefined();
});

it('should cleanup subscriptions', () => {
  const subscription = component['dataSubscription'];
  component.ngOnDestroy();
  expect(subscription.closed).toBe(true);
});
```

## Angular 20 Breaking Changes: Stricter Change Detection

**NEW in Angular 20**: Effects with change detection triggers now consistently throw NG0101 errors.

### Change Detection Triggers Requiring `untracked()`

1. **BehaviorSubject/Subject operations**:
```typescript
// CAUSES NG0101 in Angular 20
effect(() => {
    const value = this.$someSignal();
    this.someSubject$.next(true);  // Triggers change detection
});

// ANGULAR 20 FIX
effect(() => {
    const value = this.$someSignal();
    untracked(() => {
        this.someSubject$.next(true);  // Safe
    });
});
```

2. **Router navigation methods**:
```typescript
// CAUSES NG0101 in Angular 20
effect(() => {
    const shouldRedirect = this.$shouldRedirect();
    if (shouldRedirect) this.router.navigate(['/login']);  // Triggers change detection
});

// ANGULAR 20 FIX
effect(() => {
    const shouldRedirect = this.$shouldRedirect();
    untracked(() => {
        if (shouldRedirect) this.router.navigate(['/login']);  // Safe
    });
});
```

3. **Form mutations (combine with {emitEvent: false})**:
```typescript
// ANGULAR 20 BEST PRACTICE: Use BOTH safeguards
effect(() => {
    const value = this.$someSignal();

    untracked(() => {
        // Both untracked() AND {emitEvent: false} for maximum protection
        this.form.patchValue({field: value}, {emitEvent: false});
    });
});
```

4. **HTTP subscriptions with queueMicrotask()**:
```typescript
// CAUSES NG0101 in Angular 20
constructor() {
    effect(() => {
        const id = this.$photoId();

        untracked(() => {
            this.photoService.getPhoto(id)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(photo => {
                    this.$photo.set(photo);  // Signal update during CD cycle
                });
        });
    });
}

// ANGULAR 20 FIX: Wrap signal updates in queueMicrotask()
constructor() {
    effect(() => {
        const id = this.$photoId();

        untracked(() => {
            this.photoService.getPhoto(id)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(photo => {
                    queueMicrotask(() => {  // Defer signal update
                        this.$photo.set(photo);
                    });
                });
        });
    });
}
```

### Angular 20 Best Practice Pattern

```typescript
effect(() => {
    // 1. Track signal dependencies OUTSIDE untracked()
    const value = this.$inputSignal();
    const otherValue = this.$localSignal();

    // 2. Execute side effects INSIDE untracked()
    untracked(() => {
        // BehaviorSubject operations
        this.loading$.next(true);

        // Router navigation
        this.router.navigate(['/path']);

        // Form mutations (use {emitEvent: false} as additional safeguard)
        this.form.patchValue({field: value}, {emitEvent: false});
    });
});
```

### Migration Checklist for Angular 20

When reviewing or fixing effects:
- [ ] Wrap BehaviorSubject `.next()` calls in `untracked()`
- [ ] Wrap router navigation methods in `untracked()`
- [ ] Use `{emitEvent: false}` on ALL form mutations in effects
- [ ] Wrap HTTP subscription signal updates in `queueMicrotask()`
- [ ] Keep signal dependency tracking OUTSIDE `untracked()` block

## Examples

**User says**: "My component has an infinite loop after migration"
1. Search for `effect(` in the component -- find 3 effects
2. Check each: does it mutate a signal it depends on? -> Effect #2 does: reads `$count()` and sets `$count.set()`
3. Fix: separate dependency tracking from mutation, use different signal for output
4. Verify: `fixture.detectChanges()` + `TestBed.flushEffects()` completes without timeout

**User says**: "Getting ObjectUnsubscribedError in production"
1. Find effect with subscription: `effect(() => { this.service.getData().subscribe(...) })`
2. Check cleanup: no `takeUntilDestroyed` or `onCleanup` -> subscription leaks
3. Fix: add `.pipe(takeUntilDestroyed(this.destroyRef))` before `.subscribe()`
4. Verify: component destroy cleans up subscription

**User says**: "NG0101 error after Angular 20 upgrade"
1. Find effect triggering change detection: `this.loading$.next(true)` inside effect
2. Fix: wrap in `untracked(() => { this.loading$.next(true); })`
3. For HTTP subscriptions with signal updates: wrap in `queueMicrotask()`
4. Verify: no NG0101 in console

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `Maximum call stack exceeded` | Effect mutates the signal it depends on | Use separate signals for input/output of effect |
| `ObjectUnsubscribedError` | Subscription outlives component lifecycle | Add `takeUntilDestroyed(this.destroyRef)` |
| `NG0101: tick is called recursively` | Effect triggers change detection (Angular 20) | Wrap side effects in `untracked()` |
| Form patchValue triggers infinite loop | Missing `{emitEvent: false}` | Add `{emitEvent: false}` to ALL `patchValue` in effects |

## See Also

- **signal-patterns** — General signal/computed/effect patterns, mutation detection, parent-child communication
- **test-creation** — Testing effects safely (NG0101 avoidance, flushEffects patterns)
