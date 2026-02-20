---
name: chrome-devtools-debugging
description: "Browser debugging with Chrome DevTools MCP. Use for UI issues, unexpected API requests, wrong payloads, UI debugging, network request inspection, console errors, page snapshots, browser automation, UI validation testing, CSS layout debugging, or visual regression testing."
triggers:
  - "UI issue"
  - "button not working"
  - "API request"
  - "wrong payload"
  - "network request"
  - "console error"
  - "browser"
  - "screenshot"
  - "snapshot"
  - "page not loading"
  - "value reverts"
  - "inspect"
  - "DevTools"
  - "UI not updating"  # For browser-side inspection; use signal-patterns for code-level signal mutation issues
  - "422 error"
  - "visual"
negative_triggers:
  - "Python"
  - "backend only"
  - "scoring engine"
  - "database migration"
  - "CLI command"
---

# Chrome DevTools MCP Debugging

## When to Use (PROACTIVE)

Use Chrome DevTools MCP **IMMEDIATELY** when user reports:
- UI behavior issues (button not working, state not updating)
- Unexpected API requests or wrong payloads
- UI not updating after actions
- Visual/layout problems
- "Value reverts" / "signal not updating" symptoms
- Console errors in the browser

**Investigation-first approach**: Understand root cause via MCP debugging BEFORE attempting code fixes.

## Core Debugging Workflow

```
1. list_pages         -> Find/select the right page
2. navigate_page      -> Go to target URL
3. wait_for           -> Wait for page content to load
4. take_snapshot      -> Get element UIDs (prefer over screenshot)
5. list_network_requests -> Check API calls
6. get_network_request   -> Inspect specific request/response payload
7. list_console_messages -> Check for errors/warnings
8. click / fill / fill_form -> Interact with UI
9. take_snapshot      -> Verify state after interaction
```

### Navigation

```typescript
// Navigate to Angular SPA page
mcp__chrome-devtools__navigate_page({
    url: "http://localhost:4200/gallery"
});

// Wait for content to load
mcp__chrome-devtools__wait_for({ text: "Expected text on page", timeout: 10000 });

// Reload current page
mcp__chrome-devtools__navigate_page({ type: "reload" });
```

**Key URLs:**
- Production (API + SPA): `http://localhost:5000` (via `python viewer.py`)
- Angular dev server: `http://localhost:4200` (via `npx ng serve`, proxies API to 8000)
- API endpoints: `http://localhost:5000/api/*`

**Angular Router Links**: Clicking Angular `routerLink` elements via MCP `click` may not trigger navigation. Use `navigate_page` with the direct URL as a reliable fallback.

### Page Management

```typescript
// List all open pages
mcp__chrome-devtools__list_pages();

// Select a specific page (by page ID)
mcp__chrome-devtools__select_page({ pageId: 2 });

// Open new page
mcp__chrome-devtools__new_page({ url: "http://localhost:4200/gallery" });
```

## Network Request Inspection

**Use when**: API calls not happening, wrong payload sent, unexpected responses.

### List Requests (Filter by Type)

```typescript
// All fetch/XHR requests (most useful for API debugging)
mcp__chrome-devtools__list_network_requests({ resourceTypes: ["fetch", "xhr"] });

// All requests since last navigation
mcp__chrome-devtools__list_network_requests();

// Paginated (for many requests)
mcp__chrome-devtools__list_network_requests({ pageSize: 20, pageIdx: 0 });
```

### Inspect Request Details

```typescript
// Get full request/response for a specific request
mcp__chrome-devtools__get_network_request({ reqid: 42 });

// Save response body to file for large payloads
mcp__chrome-devtools__get_network_request({
    reqid: 42,
    responseFilePath: "/tmp/response.json"
});

// Save request body to file
mcp__chrome-devtools__get_network_request({
    reqid: 42,
    requestFilePath: "/tmp/request.json"
});
```

### Network Debugging Workflow

```
1. list_network_requests({ resourceTypes: ["fetch"] })  -> Find the API call
2. get_network_request({ reqid: N })                     -> Check payload & status
3. Compare request body with expected payload
4. Check response status code and body
5. If missing: interact with UI -> list_network_requests again -> verify call was made
```

**Common findings**:
- Request payload has wrong property names -> check serialization/model
- Request not sent at all -> check event handlers, disabled state
- 422 error -> check FastAPI validation (Pydantic model mismatch)
- Request sent twice -> check for duplicate signal effects or subscriptions

## Form & UI Debugging

```typescript
// Take snapshot -- returns element tree with UIDs
mcp__chrome-devtools__take_snapshot();

// Interact with form
mcp__chrome-devtools__fill({ uid: "input_uid", value: "new value" });
mcp__chrome-devtools__click({ uid: "button_uid" });

// Fill multiple fields at once
mcp__chrome-devtools__fill_form({
    elements: [
        { uid: "field1_uid", value: "value1" },
        { uid: "field2_uid", value: "value2" }
    ]
});

// Verify state changed
mcp__chrome-devtools__take_snapshot();
```

For validation testing workflows, toggle debugging, and value revert detection, see `references/validation-testing.md`.

## Console Error Monitoring

```typescript
// All console messages
mcp__chrome-devtools__list_console_messages();

// Only errors
mcp__chrome-devtools__list_console_messages({ types: ["error"] });

// Errors and warnings
mcp__chrome-devtools__list_console_messages({ types: ["error", "warn"] });

// Get full details of a specific message
mcp__chrome-devtools__get_console_message({ msgid: 5 });

// Include messages from previous navigations
mcp__chrome-devtools__list_console_messages({ includePreservedMessages: true });
```

**Look for**: Angular errors (NG0101, NG0951), effect issues, signal errors, HTTP errors.

## CSS Layout Debugging

For flex height chain diagnostics, overflow chain break detection, and responsive breakpoint testing, see the **css-layout-patterns** skill which has comprehensive diagnostic scripts and fix patterns.

## Performance Tracing

```typescript
// Start recording (with auto-reload and auto-stop)
mcp__chrome-devtools__performance_start_trace({ reload: true, autoStop: true });
// Returns: insight sets with CWV scores

// Manual trace control
mcp__chrome-devtools__performance_start_trace({ reload: false, autoStop: false });
// ... interact with page ...
mcp__chrome-devtools__performance_stop_trace({ filePath: "trace.json.gz" });

// Analyze specific insight
mcp__chrome-devtools__performance_analyze_insight({
    insightSetId: "insight-set-id",
    insightName: "LCPBreakdown"
});
```

## evaluate_script Patterns

```typescript
// Pass element UIDs to evaluate_script
mcp__chrome-devtools__evaluate_script({
    function: `(el) => { return el.innerText; }`,
    args: [{ uid: "element_uid" }]
});
```

For component state inspection, simulate input, value revert detection, and instance counting patterns, see `references/evaluate-script-patterns.md`.

## Screenshots & Snapshots

- **Snapshot** (`take_snapshot`): Structural verification -- attributes, text, UIDs. **Preferred for debugging.**
- **Screenshot** (`take_screenshot`): Visual verification -- colors, layout, styling.

```typescript
mcp__chrome-devtools__take_screenshot({ fullPage: true });
mcp__chrome-devtools__take_screenshot({ uid: "element_uid" });
mcp__chrome-devtools__take_screenshot({ filePath: "/tmp/debug-screenshot.png" });
```

## Dialog Handling

```typescript
// Accept alert/confirm dialog
mcp__chrome-devtools__handle_dialog({ action: "accept" });

// Dismiss dialog
mcp__chrome-devtools__handle_dialog({ action: "dismiss" });

// Enter text in prompt dialog
mcp__chrome-devtools__handle_dialog({ action: "accept", promptText: "user input" });
```

## Keyboard Interaction

```typescript
// Press Enter to submit
mcp__chrome-devtools__press_key({ key: "Enter" });

// Keyboard shortcuts
mcp__chrome-devtools__press_key({ key: "Control+A" });
mcp__chrome-devtools__press_key({ key: "Tab" });
mcp__chrome-devtools__press_key({ key: "Escape" });
```

## Configuration

**Recommended** (in `.claude/settings.json`):
```json
{
  "chrome-devtools": {
    "command": "npx",
    "args": ["chrome-devtools-mcp@latest", "--isolated=true", "--headless=false", "--channel=stable", "--viewport=1920x1080"]
  }
}
```

All chrome-devtools tools are pre-approved via `mcp__chrome-devtools__*` wildcard.

## Timeout Handling

```
Attempt 1 timeout -> retry same operation
Attempt 2 timeout -> list_pages() to check connection, retry
After 2-3 failures -> fail fast, report to user
```

**Never loop indefinitely** on MCP timeouts.

## Troubleshooting

| Issue | Solution |
|-------|---------|
| Element not found | Take fresh snapshot -- UIDs change after DOM updates |
| Timeout on operations | Retry 2-3 times, then `list_pages` to verify connection |
| Connection refused | Restart Claude Code session after MCP config changes |
| Changes don't take effect | Add `wait_for` after navigation; verify content loaded |
| Stale UIDs | Always take new snapshot before interacting |
| Screenshot shows cached state | Navigate away and back; use `--isolated=true` |

## Common Debugging Scenarios

### API Not Called After UI Action
1. `take_snapshot` -> find button UID
2. `click` -> interact with UI
3. `list_network_requests({ resourceTypes: ["fetch"] })` -> check if request made
4. If missing: check disabled button, event handlers, signal state

### Wrong API Payload
1. `list_network_requests({ resourceTypes: ["fetch"] })` -> find the request
2. `get_network_request({ reqid: N })` -> inspect request body
3. Compare with expected payload
4. Check serialization code and FastAPI Pydantic models

### UI Not Updating After Action
1. `click` or `fill` -> perform the action
2. `take_snapshot` -> check if DOM updated
3. `list_console_messages({ types: ["error"] })` -> check for Angular errors
4. If stale: check signal updates, effect patterns, zoneless change detection triggers

### Signal State Not Reflecting
1. `evaluate_script` -> inspect DOM values
2. `list_console_messages({ types: ["error"] })` -> check for NG0101 (effect CD issue)
3. If NG0101: check for missing `untracked()` in effects (Angular 20 stricter CD)
4. If stale: verify `computed()` dependencies are correct

## Examples

**User says**: "The save button doesn't do anything when I click it"
1. `navigate_page` to the target URL, `wait_for` content to load
2. `take_snapshot` to find the button UID and check if it has `disabled` attribute
3. `click` the button
4. `list_network_requests({ resourceTypes: ["fetch"] })` to check if API call was made
5. If no request: inspect button event handler and signal state in code

**User says**: "The API returns 422 when I submit the form"
1. `list_network_requests({ resourceTypes: ["fetch"] })` to find the failing request
2. `get_network_request({ reqid: N })` to inspect the request payload and response body
3. Compare payload with FastAPI Pydantic model to identify field mismatch
4. Fix serialization in Angular service or Pydantic model validation

**User says**: "I see a console error in the browser"
1. `list_console_messages({ types: ["error"] })` to get all errors
2. `get_console_message({ msgid: N })` for full error details
3. Identify if it's an Angular error (NG0101, NG0951), HTTP error, or runtime error
4. Use the error message to locate and fix the root cause in code
