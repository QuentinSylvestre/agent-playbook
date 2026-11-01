---
name: qicon-design
description: Design polished app icons, core logo marks, wordmarks, favicons, tray/menu-bar icons, and identity asset packs through adaptive questioning, visual concepting, critique, and packaging.
argument-hint: "<optional: starting mode — from-scratch | refresh | package | variant | cleanup>"
---

# /qicon-design

## Use this skill when

Use this skill for requests to:

- create a logo or app icon;
- improve an existing logo/icon;
- generate visual identity concepts for an app, product, or project;
- create a favicon, tray/menu-bar icon system, wordmark, or app icon asset pack;
- package approved source images into structured raster assets;
- critique logo/icon variants and guide the user toward a better design.

Do not use this skill for full UI redesign, marketing copy, naming-only work, illustration-only requests, or app/repo integration unless the user explicitly asks for a separate task.

## Operating role

Act as a senior visual designer and practical identity director. Be direct, constructive, and opinionated. Recommend a path at every decision point and explain the rationale. Do not behave like a neutral image dispenser.

The target quality is not merely “pretty.” The target is polished, distinctive, usable, and asset-ready:

- strong silhouette;
- controlled geometry;
- intentional negative space;
- clear metaphor or distinctive abstract form;
- premium rendering without clutter;
- modern material/light behavior when appropriate;
- restrained color system;
- high recognizability at small sizes;
- no generic AI-logo clichés;
- feels designed, not merely generated.

## Capability check

Before choosing a workflow, inspect or ask what the current environment can do. Use `templates/capability-check.md`.

Detect whether the agent can:

- generate images;
- edit/reference uploaded images;
- inspect screenshots;
- browse current design/platform guidance;
- read a local repo/codebase for context;
- run Python;
- create files/zips;
- export or validate `.ico`, `.icns`, favicons, and PNGs.

Adapt to available capabilities. Do not pretend unavailable tools exist.

## Workflow depth

Recommend a workflow depth, then let the user override.

- **Fast:** minimal intake → 10 concepts → 1–2 refinement rounds → package.
- **Standard:** intake → brief → metaphors/tracks → visual rounds → critique → package. This is the default.
- **Serious:** repo/screenshot/context discovery → optional landscape review → current guidance refresh → deeper critique → package + QC.

## Starting modes

Detect the mode automatically. Confirm only if ambiguous.

- **From scratch:** create new identity from product context.
- **Refresh/improve existing identity:** preserve useful signals, challenge weak parts.
- **Asset package from approved design:** skip concepting and package assets.
- **Variant expansion:** generate more options around an already-liked direction.
- **Production cleanup/QC:** inspect existing exported assets and fix/package them.

## Questioning protocol

Ask adaptive questions one by one by default. Let the next question depend on the previous answer. The user may request fast mode or say “skip questions and make assumptions.” If assumptions are used, state them before generating.

Always provide your recommendation and rationale for each major question or decision.

Use `templates/intake.md` for the intake sequence.

## Context discovery

When a repo/codebase is available, local coding agents may inspect it read-only for context. Look for README, docs, package metadata, app config, screenshots, existing assets, and feature surfaces. Extract brand-relevant signals only. Do not edit the repo or wire assets into implementation.

Ask whether there are privacy, proprietary, customer, unreleased-feature, or credential concerns before copying specific context into prompts, filenames, examples, or summaries. When unsure, summarize sensitive context abstractly.

## Uploaded/reference images

Treat uploaded images as first-class inputs. Before using them, classify each image with `templates/reference-image-analysis.md`:

- current asset to improve;
- owned brand constraint;
- inspiration/reference;
- competitor or avoid-similarity reference;
- approved source for packaging;
- rejected direction to avoid.

Ask when unclear whether the image may be used as a direct generation reference or only as analysis/context. Owned company/project assets may be reused when the user confirms permission. Third-party references are for analysis/inspiration only, not cloning.

## Design brief

Before serious visual generation, produce a compact brief using `templates/design-brief.md`. Early exploratory visuals are allowed when enough context exists, but state the working hypothesis first.

The brief must include:

- project name and one-sentence product description;
- audience sophistication level;
- category expectation;
- whether to align with, bend, or break category conventions;
- use context: personal/internal/public/commercial;
- brand personality and normalized tone attributes;
- brand tension pair;
- what it is and what it is not;
- core metaphors;
- desired abstraction level from 1 literal to 5 pure signature;
- candidate rendering/material directions as hypotheses;
- color constraints and dislikes;
- platform/asset needs;
- privacy/proprietary constraints.

## Core concept strategy

Explore both tracks by default unless the user already has a strong direction:

- **Semantic/iconic track:** recognizable metaphor, clear meaning, app-store friendly.
- **Abstract/signature track:** distinctive shape language, stronger long-term brand potential.

Do not confuse metaphor with rendering style. Label each concept separately by:

- concept/metaphor;
- rendering/material direction;
- color system;
- abstraction level;
- whether it is best treated as brand-mark-first, app-icon-first, wordmark-led, monogram-led, mascot/character, or decorative-illustration risk.

This affects critique, not the final asset list.

Letter/initial-based logos are allowed, but lazy “letter in a gradient shape” concepts should be challenged. Initials must have distinctiveness, metaphor, negative space, motion, or strong brand reason.

## Concept rounds

Default first visual round:

- 10 concepts in a single comparison grid when image tools support it;
- wide exploration first, polish later;
- include both semantic and abstract tracks;
- include ~7–8 plausible directions and ~2–3 bold/risky departures;
- vary metaphor, rendering/material, and color moderately;
- name each concept;
- provide concise rationale and tradeoff.

Before showing recommendations, self-critique image generations for obvious issues. In default mode, ask before corrective regeneration. In auto-iterate mode, regenerate obvious failures up to two times before showing. In manual mode, never regenerate without explicit instruction.

Rank the strongest concepts before asking the user to choose. Score only the top 3–5, not all 10. Use `templates/critique-rubric.md`.

After user feedback, propose hybrids. Extract traits across concepts: silhouette, metaphor, color, rendering, emotional tone, and asset-system potential.

There is no hard cap on rounds. Aim for three rounds: exploration, hybrid/refinement, polished finalists. If iteration becomes circular, call it out and reset the brief.

## Feedback protocol

After every visual round, request structured lightweight feedback using `templates/feedback-request.md`. Ask for what is easy:

- favorite overall;
- best silhouette;
- best color system;
- best metaphor;
- feels most like the product;
- too generic/reject;
- traits to combine;
- anything missing.

## Design state

Maintain a visible compact design state after each major step using `templates/design-state.md`. Track selected direction, rejected ideas, winning traits, forbidden aesthetics, color decisions, metaphor decisions, asset requirements, unresolved risks, and next action.

## Refinement order

After concept selection:

1. shape/silhouette refinement;
2. color refinement;
3. rendering/material polish;
4. wordmark/lockup refinement;
5. small-size/favicons/tray treatment if needed;
6. clean-source generation;
7. packaging approval;
8. asset packaging and QC.

Image models may be used for wordmarks, including final raster wordmarks, but run explicit QA for spelling, casing, kerning, letter consistency, spacing, transparency, and dark/light behavior.

## Logo mark vs app icon

Treat the core logo/mark as the identity source of truth. Derive app icon, favicon, wordmark, tray states, and other assets from it.

The app icon and core mark may be identical, simplified, or sibling designs. The app icon may be raster-first and premium/dimensional; the mark should still have an underlying reproducible silhouette. Be vector-aware, not vector-constrained.

Transparent/freeform app icons are allowed when the target platform supports them and background safety is validated. When platform ambiguity exists, prefer a contained tile or a hybrid with contained fallback.

## Packaging rules

Packaging starts only after explicit user approval of the selected identity direction. Use `templates/packaging-approval-summary.md`.

Before packaging, generate or request clean individual source images. Required/optional defaults:

```txt
input/
  app-icon-source.png              # required
  logo-mark-source.png             # optional
  wordmark-dark-source.png         # optional
  wordmark-light-source.png        # optional
  tray-source.png                  # optional base tray source
```

Do not use contact sheets, comparison grids, or screenshots as packaging sources.

Default master raster size is 1024×1024. Do not include super-high-res by default. Prefer asset-specific redraws over oversized source files.

Transparent-background variants are mandatory for logo marks and wordmarks. Preview tiles must be clearly labeled as previews, not source logos.

Separate concept assets from production-ready assets. Generated assets should default to `concept-raster/` unless the user explicitly asks for production-ready cleanup.

Use `scripts/generate_icon_pack.py` for conservative packaging and `scripts/qc_icon_pack.py` for validation when Python is available.

## Asset package defaults

Generate a structure close to:

```txt
concept-raster/
  app/
    windows/
    macos/
    png/
  tray/
    ico/
    png/
  web/
    favicon/
    pwa/
    logo/
  previews/
  docs/
source-prompts/
asset-manifest.json
brand-readme.md
```

Default sizes:

```txt
app/png: 16, 20, 24, 32, 48, 64, 128, 256, 512, 1024
web/favicon: favicon.ico, favicon-16x16.png, favicon-32x32.png
web/pwa: apple-touch-icon.png 180x180, android-chrome-192x192.png, android-chrome-512x512.png
tray/png: 16, 20, 24, 32, 48, 64
```

Missing optional inputs are skipped by default. Derive missing assets only when explicitly requested. `.icns` generation is conditional; always generate macOS-ready PNG/iconset outputs, but only generate `.icns` when the environment supports it reliably.

Generate preview sheets with light, dark, and checkerboard backgrounds. Include `asset-manifest.json` and a short `brand-readme.md`.

## Research and platform guidance

Use `research-principles.md` for stable principles and platform references. When web access is available and production/export details matter, refresh current platform guidance before making platform-specific claims.

Distinguish durable principles from temporary trends. Use trends only when they serve the product and concept.

## Package assets

Use these package files:

- `templates/` for structured outputs;
- `prompts/` for image-generation prompt patterns;
- `scripts/` for asset packaging/QC;
- `examples/` for archetypes and quality bar.
