---
name: qprototype
description: Build a throwaway prototype to answer a specific design question — whether a state model is correct, or what a UI should look like — before committing to an implementation. Invoke directly when you want to sanity-check a state model, explore UI options, or answer a design question before writing production code.
argument-hint: "<design question or description of what to prototype>"
---

## Your role

Your first action is to identify the design question before writing any code. Write the question down explicitly — a prototype that answers the wrong question is waste, and habit pushes toward writing code first.

Do NOT write production code immediately. This is the habitual alternative this skill overrides.

**When NOT to use this skill**: Use this skill when the implementation direction is unknown and a quick experiment would settle it. Skip this skill and go straight to `/qplan` only if the design question has already been answered (e.g., by a prior prototype, a spike, or explicit user direction). For deeper codebase uncertainty not answerable by a prototype, use `/qexplore`.

## Work to prototype

$ARGUMENTS

If `$ARGUMENTS` is empty, ask the user one question: "What design question should this prototype answer?" Treat the user's answer as `$ARGUMENTS` and proceed to Step 1.

## Step 1: State the question

Write down in one paragraph what question this prototype will answer. Make the question visible in the artifact itself — not only in a comment, but in a heading or introductory block the reader sees first. This is the check: if someone opens the prototype and cannot find the question, the question was not stated.

For UI prototypes, include the question as a code comment at the top of the variant index file or as a visible text element in the floating switcher's tooltip or label area.

Do this step first, always.

## Step 2: Pick a branch

Apply this rule in order:

1. If there is no surrounding file (standalone invocation with no codebase context), skip the file-type check below and use the **Logic branch** fallback directly.
2. Check the surrounding file type: if the work is inside a backend module, a data layer, or any non-UI code, use the **Logic branch**. If the work is inside a page, a component, or a UI layer, use the **UI branch**.
3. If the file type check does not resolve the question, use the **Logic branch** (named fallback — covers the ambiguous-file-type case and the can-not-tell case).

As a cross-check:
- "Does this logic / state model / API shape / data structure / function decomposition feel right?" → **Logic branch**
- "What should this look like?" → **UI branch**

**Conflict resolution**: if the file type and the question text point to different branches, treat the question text as the stronger signal — ask the user if reachable.

If the user is reachable and the question is genuinely ambiguous, ask before proceeding. If the user is not reachable (e.g., in a sub-agent context with no interactive channel), apply the Logic branch fallback and state the assumption at the top of the artifact.

**Mid-execution correction**: if, while building the prototype, you realize the question is better answered by the other branch, stop, re-run Step 2 explicitly, and rebuild from Step L1 or the UI branch start.

## Logic branch

Build the prototype in four steps:

**Step L1 — Isolate the logic.** Extract the logic under examination into a portable module. If the project is JS/TS, use vanilla JS or TS with no framework dependencies. For other languages, default to vanilla JS for the module and harness — the HTML file runs in any browser, regardless of the project's language — or ask the user whether to use JS or the project's native language, and document the choice in the Step 1 question block. The module has a clear input/output surface that maps to the question from Step 1.

**Step L2 — Build a browser demo harness.** Wrap the module in a browser-based harness with:
- Free-play controls: buttons that let the user call any exported function directly and see the result
- Tabbed guided walkthroughs: one tab per edge case named in the Step 1 question. If no edge cases were named, include at minimum the empty-state case and the error-state case.

**Step L3 — Render full state after every action.** This is a hard rule. After every action the user takes, render every field of the data structure or module state the prototype exercises. Not the global app store. Not a filtered or summarised output. Every field. The point of the prototype is to see the full state machine; partial output hides the answer.

**Step L4 — Package as a single self-contained HTML file.** The logic module is inlined as `<script>` blocks. No external dependencies. No `fetch` calls. No ES module imports. No APIs that fail on `file://` origins. The user double-clicks the file to open it — no install steps, no server, no build.

## UI branch

**Prefer hosting variants on an existing page** (existing-page path). Before creating a new route, ask explicitly: "Is there really no existing page this could be embedded in?" An empty route hides design problems that a populated page would expose.

**Variant count**: minimum 2, default 3, cap at 5. Use the default of 3 when the question does not specify how many alternatives to evaluate.

**`?variant=` parameter**: the value is the variant key string, not an integer index. For example: `?variant=VariantA`, not `?variant=0`.

Build the UI prototype in order:

**Step U1 — Choose the path.** Ask (or confirm) whether an existing page can host the variants. If yes, use the existing-page path. If no existing page is suitable, use the new-route path.

**Step U2 — Build the variants.** Follow the variant hard rules below.

**Step U3 — Implement the floating switcher.** Follow the floating switcher spec below.

### Existing-page path (preferred)

Variants render on the same existing route, switched by the `?variant=` URL search param. Existing data fetching, routing params, and auth stay unchanged; only the rendered subtree swaps per variant.

### New-route path (last resort)

When no existing page is suitable, create a throwaway route. Follow the project's existing routing convention. Name the route and file so it is obviously a prototype — include "prototype" in the path or filename. Register the route using the project's dev-only or feature-flag pattern if one exists; do not add a committed named route to the production router. Use the same `?variant=` switching pattern.

### Variant hard rules

- Variants must be structurally different: different layout, different information hierarchy, or different primary affordance. Different colors or copy alone is not a prototype; it is wallpaper. If two drafts come out too similar, redo one with an explicit structural constraint ("do not use a card grid").
- Each variant exports a named component: VariantA, VariantB, VariantC (and so on).
- Variants must not wire to real mutations. A mutation is "real" if it reaches a network endpoint or writes to a persistent store. In-memory state updates, mock data, and intercepted-but-never-dispatched calls are stubs and are allowed.

### Floating switcher

Implement once in a shared component; both the existing-page and new-route paths reuse it.

- Fixed-position bar, visually distinct from the page: high-contrast pill, subtle shadow
- Left/right arrows cycle through variants and wrap at the ends; the label shows the current key and exported name (example: `B — Sidebar layout`)
- Arrow clicks update the `?variant=` URL search param via the project's router — variants are shareable links and reload-stable
- For production-gating, use the project's existing environment-detection idiom if one is found; otherwise default to `process.env.NODE_ENV !== 'production'` (note: this requires bundler injection — if unavailable, inline `const IS_PROTOTYPE = true` at the top of the switcher file and condition on it)
- Keyboard: `←` and `→` cycle variants. Do NOT intercept these keys when an `<input>`, `<textarea>`, or `[contenteditable]` element is focused
- Hidden in production builds

## Shared rules

These apply to both branches:

- **Throwaway from day one, clearly marked.** Name the prototype so a casual reader immediately knows it is not production code. Include "prototype" or "PROTOTYPE" in the filename, route path, or component name.
- **Trivial to run.** One command for UI; double-click for logic. No reading required to start it.
- **No persistence by default.** State lives in memory. If the question explicitly involves persistence, use a scratch DB or local file placed next to the prototype file, named with a `PROTOTYPE_` prefix (example: `PROTOTYPE_sessions.db`).
- **Skip the polish.** No tests. No error handling beyond what makes the prototype runnable. No abstractions.
- **No real mutations.** Do not reach a network endpoint or write to a persistent store from prototype code (logic or UI branch). See the mutation definition in `## UI branch`.
- **Co-location.** Place the prototype next to the module or page it explores. Follow the project's existing routing and naming conventions.

## Step 3: Close

Present the user with these three options and wait for their choice:

**A. Commit to a throwaway branch** — prototype artifacts go into a commit on a branch the user names; the verdict goes in the commit message body. The branch must not be the production branch (main, master, or the project's primary branch). If the user names a production branch, treat this as a promotion directive and apply the governance override rule below.

**B. Keep working-tree changes locally** — no commit; write the verdict as `PROTOTYPE_VERDICT.md` placed next to the prototype file.

**C. Discard** — question answered; write `PROTOTYPE_VERDICT.md` next to the prototype file, paste its contents in chat so the user can read the verdict, then delete the prototype files.

If the user's response requests shipping, deploying, or promoting the prototype code to production, treat it as a promotion directive and apply the governance override rule below — do not silently default to option B.

If the user's response cannot otherwise be interpreted as one of the three options, default to option B and proceed.

**Verdict capture is mandatory regardless of which option is chosen.** The verdict is: the answer the prototype produced (which variant worked, whether the state model was correct, what the API shape should be) and the question it settled. Write it down.

**Never promote prototype code directly to production. The prototype is evidence, not implementation. Rewrite the validated approach properly before shipping it.** If the user explicitly directs promotion without a rewrite, flag this as a governance override and confirm before proceeding — do not refuse, but name the override explicitly.

## Rules

- Apply the **Council-Enriched Escalation** rule in `shared/AGENTS.md` when escalating design trade-offs (such as branch ambiguity or variant-count decisions) to the user.
- Do NOT write tests for prototype code.
- Do NOT add error handling beyond what makes the prototype runnable.
- Do NOT add production abstractions.
- Do NOT wire any prototype (logic or UI) to real mutations — see the mutation definition in `## UI branch`.
- Do NOT promote prototype code to production without rewriting it — see the override-confirmation rule in `## Step 3: Close`.
