## Kiro Browser-Test Discipline

Re-read `/qbrowser-test` SKILL.md in full before driving a browser surface — context pressure degrades recall of the Verification pattern, Snapshot-vs-screenshot rule, and Post-verification cleanup steps.

### Additional MCP snippets

These supplement the single MCP example in the shared MCP Browser Tools section (Loading local HTML files).

Element counting and content verification:

```javascript
async (page) => {
  await page.goto('file:///C:/path/to/file.html');
  await page.waitForLoadState('domcontentloaded');
  const count = await page.locator('.card').count();
  const texts = await page.locator('.card h2').allTextContents();
  return { count, texts };
}
```

JS error checking:

```javascript
async (page) => {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.goto('file:///C:/path/to/file.html');
  await page.waitForLoadState('domcontentloaded');
  return errors.length === 0 ? 'No JS errors' : errors;
}
```

### Additional Standalone Script snippets

These supplement the single script example in the shared Standalone Scripts section (Static HTML testing).

Dynamic webapp testing:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")

    page.click("button#submit")
    page.wait_for_selector(".result")
    assert page.locator(".result").text_content() == "Success"

    browser.close()
```

Console log capture:

```python
from playwright.sync_api import sync_playwright

errors = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto("file:///C:/path/to/file.html")
    page.wait_for_load_state("domcontentloaded")
    browser.close()

assert not errors, f"JS errors: {errors}"
```

_This overlay cites shared `/qbrowser-test` SKILL.md sections by name (MCP Browser Tools, Standalone Scripts), per `shared/AGENTS.md § SKILL.md Authoring` — never by section or step number (desync guard)._
