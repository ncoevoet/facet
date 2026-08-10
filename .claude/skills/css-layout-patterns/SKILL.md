---
name: css-layout-patterns
description: "CSS and Tailwind v4 layout patterns. Use for @apply not working in SCSS, @reference tailwindcss, flex height chain, overflow not working, flex:1 in flex-row, the page scrolling instead of the container, dark theme styling, responsive/breakpoint work, min-height issues, or flex layout debugging. Do NOT use for signals/effects/computed, Python or backend code, tests/specs, or API work."
---

# CSS & Layout Patterns

## Theme

Facet uses a dark theme with Angular Material and Tailwind v4:
- **Background**: `#0b0b0b` (near-black)
- **Primary**: Material green palette
- **Accent**: Cyan highlights
- All components should assume dark background. Use light text colors, subtle borders (`border-white/10`), and translucent hover states (`hover:bg-white/[0.08]`).

## Tailwind v4: @apply in SCSS (CRITICAL)

All component SCSS files using `@apply` MUST include `@reference` as the **first line**:

```scss
@reference "tailwindcss";

.my-class {
    @apply flex items-center gap-2;
}
```

Without `@reference "tailwindcss";`, `@apply` directives won't resolve in Tailwind v4.

### Common Errors
- **`@apply` silently ignored**: No error, styles just don't apply -- always check for missing `@reference`
- **Order matters**: `@reference` must come BEFORE any `@apply` usage
- **Per-file requirement**: Each `.scss` file needs its own `@reference`, not just the root

### Checking a Component
```bash
# Find SCSS files using @apply without @reference
grep -rn "@apply" client/src/ --include="*.scss" -l | xargs grep -L "@reference"
```

## Tailwind-First Rule (CRITICAL)

**Never create custom SCSS classes** when a standard Tailwind utility exists:

| Bad (custom SCSS) | Good (Tailwind) |
|---|---|
| `.detail-section { margin-bottom: 24px }` | `mb-6` |
| `.clickable-row { cursor: pointer; &:hover { background: rgba(255,255,255,0.08) } }` | `cursor-pointer hover:bg-white/[0.08]` |
| `.text-center { text-align: center }` | `text-center` |
| `.full-width { width: 100% }` | `w-full` |
| `h3 { margin-bottom: 16px; font-weight: 500 }` | `mb-4 font-medium` on `<h3>` |

**When touching a component's template/SCSS**:
1. Check SCSS for custom classes replaceable by Tailwind
2. Flag hardcoded pixel values -- use Tailwind spacing (`mb-4`, `p-2`, `gap-2`)
3. Keep SCSS empty if all styling is achievable via Tailwind classes

## Flex Height Chain Pattern

**Problem**: Page scrolls instead of container scrolling

Every element from viewport to scroll container must maintain the flex chain:

```
viewport -> html -> body -> app-root -> main -> content -> scroll-container
```

Each element needs:
```css
display: flex;
flex-direction: column;
flex: 1;
min-height: 0; /* CRITICAL - allows flex children to shrink */
overflow: hidden; /* or auto on the scroll container */
```

### flex-row vs flex-col Height Control

| Parent Direction | Child Height Control | Why |
|:---|:---|:---|
| `flex-direction: column` | `flex: 1` | Main axis is vertical -> flex controls height |
| `flex-direction: row` | `height: 100%` | Main axis is horizontal -> flex controls width only |

**Common mistake**: `flex: 1` in a flex-row parent does NOT constrain height!

### Columns Don't Fill Width

Add `width: 100%` to elements in flex-row containers.

### Finding Chain Breaks

Look for elements where `clientHeight > parentHeight`:
```
{ name: '.gallery-grid', height: 3200, parentHeight: 708, overflows: true }
//                        ^^^^         ^^^^                ^^^^^^^^^^^^
// This element needs height constraint
```

## Tailwind Group-Scoped Hover

Use named groups to scope hover effects to specific areas (e.g., image-only overlay, not the entire card):

```html
<!-- group/card wraps the whole card, group/img wraps just the image -->
<div class="group/card rounded-lg overflow-hidden">
  <div class="group/img relative">
    <img src="..." class="w-full" />
    <!-- This overlay only appears when hovering the image area -->
    <div class="absolute inset-0 bg-black/50 opacity-0 group-hover/img:opacity-100 transition-opacity">
      ...action buttons...
    </div>
  </div>
  <!-- Tags/details below — NOT affected by image hover -->
  <div class="p-2">tags, scores, etc.</div>
</div>
```

## mat-icon Centering in Small Containers

`mat-icon` has default line-height that misaligns in small round buttons. Fix:

```html
<!-- Container: use inline-flex, not flex -->
<button class="w-7 h-7 rounded-full inline-flex items-center justify-center">
  <!-- Icon: override size AND line-height -->
  <mat-icon class="!text-base !w-4 !h-4 !leading-4">star</mat-icon>
</button>
```

## Common Mistake Reference

| Symptom | Cause | Fix |
|---------|-------|-----|
| Page scrolls instead of container | Missing height constraint in chain | Add `flex: 1` or `height: 100%` |
| Content clipped unexpectedly | Missing `min-height: 0` | Add `min-height: 0` |
| `flex: 1` doesn't constrain height | Parent is flex-row | Use `height: 100%` instead |
| Columns don't fill width | Missing width constraint | Add `width: 100%` |
| `@apply` doesn't work | Missing `@reference` | Add `@reference "tailwindcss";` first line |
| Overflow not scrolling | Missing `min-height: 0` on parent | Add to all flex ancestors |
| Dark theme text invisible | Using default dark text on dark bg | Use `text-white` or `text-white/70` |

## Diagnostic Script (Chrome DevTools MCP)

```typescript
// Quick page-level check
() => {
  const body = document.body;
  const scrollContainer = document.querySelector('.scroll-container');
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    pageScrolls: body.scrollHeight > body.clientHeight,
    containerScrolls: scrollContainer ?
      scrollContainer.scrollHeight > scrollContainer.clientHeight : 'not found',
    issue: body.scrollHeight > body.clientHeight ?
      'Page scrolling - check flex height chain' : 'Container scrolling - OK'
  };
}
```

```typescript
// Detailed chain trace -- find where chain breaks
() => {
  const selectors = ['app-root', 'main', '.content', '.gallery-grid', '.scroll-container'];
  return selectors.map(sel => {
    const el = document.querySelector(sel);
    if (!el) return { name: sel, error: 'not found' };
    const style = getComputedStyle(el);
    return {
      name: sel,
      height: el.clientHeight,
      parentHeight: el.parentElement?.clientHeight || 0,
      overflows: el.clientHeight > (el.parentElement?.clientHeight || 0),
      display: style.display,
      flexDirection: style.flexDirection,
      flex: style.flex,
      minHeight: style.minHeight,
      overflow: style.overflow
    };
  });
}
```

## Debugging Steps

1. Run `mcp__chrome-devtools__evaluate_script` with the diagnostic script
2. Find which element breaks the chain (child height > parent height)
3. Check parent's `flex-direction` to determine fix:
   - Column parent -> add `flex: 1; min-height: 0;` to child
   - Row parent -> add `height: 100%; min-height: 0;` to child
4. Add `overflow: hidden` to containers, `overflow-y: auto` to scroll target
5. Verify at multiple breakpoints (mobile, tablet, desktop)

## Responsive Testing Breakpoints

```typescript
// Standard Tailwind v4 breakpoints
// sm: 640px, md: 768px, lg: 1024px, xl: 1280px, 2xl: 1536px

// Test at common sizes via Chrome DevTools MCP:
mcp__chrome-devtools__resize_page({ width: 1920, height: 1080 }); // Desktop
mcp__chrome-devtools__resize_page({ width: 1280, height: 800 });  // Laptop
mcp__chrome-devtools__resize_page({ width: 768, height: 1024 });  // Tablet
mcp__chrome-devtools__resize_page({ width: 375, height: 667 });   // Mobile
```

## Examples

**User says**: "@apply isn't working in my component SCSS"
1. Check the SCSS file for `@reference "tailwindcss";` as the first line
2. If missing, add it before any `@apply` usage
3. Verify each SCSS file has its own `@reference` (per-file requirement)

**User says**: "The page scrolls instead of just the gallery grid"
1. Run the flex height chain diagnostic script via Chrome DevTools MCP
2. Find the element where `overflows: true` -- that's where the chain breaks
3. Check parent's `flex-direction`: column -> add `flex: 1; min-height: 0;`; row -> add `height: 100%; min-height: 0;`
4. Add `overflow-y: auto` on the intended scroll container
5. Verify at desktop and mobile breakpoints

**User says**: "Should I use custom SCSS or Tailwind classes?"
1. Always prefer Tailwind utility classes over custom SCSS
2. Check if a standard Tailwind class exists for the desired style
3. Only write custom SCSS when Tailwind cannot express the pattern (e.g., complex selectors, ::ng-deep)
