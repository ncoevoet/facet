# Angular 20 Breaking Changes: Stricter Change Detection

**NEW in Angular 20**: Effects with change detection triggers now consistently throw NG0101 errors.

## Contents

- [Change Detection Triggers Requiring `untracked()`](#change-detection-triggers-requiring-untracked)
- [Best Practice Pattern](#best-practice-pattern)
- [Migration Checklist](#migration-checklist)

## Change Detection Triggers Requiring `untracked()`

### 1. BehaviorSubject/Subject operations
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

### 2. Router navigation methods
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

### 3. Form mutations (combine with {emitEvent: false})
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

### 4. HTTP subscriptions with queueMicrotask()
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

## Best Practice Pattern

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

## Migration Checklist

When reviewing or fixing effects:
- [ ] Wrap BehaviorSubject `.next()` calls in `untracked()`
- [ ] Wrap router navigation methods in `untracked()`
- [ ] Use `{emitEvent: false}` on ALL form mutations in effects
- [ ] Wrap HTTP subscription signal updates in `queueMicrotask()`
- [ ] Keep signal dependency tracking OUTSIDE `untracked()` block
