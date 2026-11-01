# Presentation Design Guidance

*Last reviewed: 2026-06-12*

Original palette selections — these are curated color combinations, not sourced from any proprietary material.

## Color Palette Selection

### Principles

1. **Topic-informed** — choose a palette that resonates with the subject (finance = navy/gold, tech = blue/cyan, health = green/white)
2. **Dominance over equality** — one primary color dominates (60%), one secondary supports (30%), accents highlight (10%)
3. **Dark/light contrast** — ensure text is always readable against its background (minimum 4.5:1 contrast ratio)
4. **Limit to 4-5 colors** — more causes visual noise

### Design Directions

Pick by audience first: **safe** for internal or conservative audiences, **bold** for launches and keynotes, **refined** for senior or editorial audiences, **contrarian** when the deck must look unlike everyone else's. Each tone has 5 directions — 20 total. Each direction is a starting point; adapt to the brand's own colours once the mood is established.

| Direction | Tone | Mood | Accent on Background | Suits |
|---|---|---|---|---|
| Clean Corporate | safe | calm, trustworthy | #1F5FAD on #FFFFFF | KPI slides, charts, comparisons, process flows |
| Quiet Neutral | safe | understated | #2F6F5E on #FAFAF8 | text-heavy slides, tables, charts |
| Public Sector | safe | plain, accessible | #005EA5 on #FFFFFF | process flows, bullet lists, tables |
| Consulting Blue | safe | structured, analytical | #0B3D91 on #FFFFFF | matrix comparisons, charts, analytical comparisons |
| Teaching Friendly | safe | warm, step-by-step | #0E7C66 on #FFFDF7 | process flows, timelines, bullet lists |
| Bold Signal | bold | one loud colour | #D7261E on #FFFFFF | hero stat slides, statement slides, KPI decks |
| Dark Stage | bold | keynote dark stage | #35C2A0 on #121417 | statement slides, hero stats, pull quotes |
| Electric Launch | bold | energetic launch | #5B2EE5 on #FFFFFF | image+text layouts, hero numbers, side-by-side comparisons |
| Sunset Warm | bold | optimistic, human | #C2410C on #FFF8F1 | pull quotes, statement slides, image+text layouts |
| Data Dense | bold | dashboards | #0F766E on #F7F9FA | KPI dashboards, charts, data tables |
| Editorial Serif | refined | long-form magazine | #8B1E3F on #FBF9F5 | pull quotes, editorial statements, image features |
| Gallery White | refined | airy, few words | #3A3A3A on #FFFFFF | image+text layouts, statement slides, section breaks |
| Boardroom | refined | formal, senior audience | #8A6D1D on #FDFCF8 | executive KPIs, comparisons, data tables |
| Nordic Calm | refined | soft, natural | #3E6B5B on #F4F1EC | timelines, process flows, statement slides |
| Ink and Paper | refined | monochrome, deep accent | #1E3A5F on #FFFFFF | pull quotes, text lists, comparisons |
| Brutalist Mono | contrarian | raw, typewriter | #000000 on #F2F2EE | statement slides, text lists, process flows |
| Poster Yellow | contrarian | loud poster | #111111 on #FFD60A | bold statements, hero stats, section dividers |
| Night Terminal | contrarian | engineering console | #4ADE80 on #0B0F0C | process flows, timelines, hero stats |
| Blueprint | contrarian | technical drawing | #FFD166 on #0E3A68 | process diagrams, matrices, timelines |
| Risograph | contrarian | zine print, two inks | #D6336C on #FFF4E6 | pull quotes, statement slides, comparisons |

### Using Design Directions

- **Slide backgrounds**: use the **background** hex from the Accent on Background column (e.g., `#FFFFFF` for light themes, `#121417` for dark themes)
- **Titles**: use the **accent** hex from the Accent on Background column; let Tone and Mood guide the direction choice
- **Body text**: light gray (`e0e0e0`–`f5f5f5`) on dark, dark gray (`363636`–`4a4a4a`) on light
- **Accent**: call-to-action elements, key metrics, chart highlights, section dividers

## Per-Slide Design Rules

### Every slide must have a visual element

Never produce a text-only slide. Each slide includes at least ONE of:
- Chart or data visualization
- Image or icon
- Shape-based layout (cards, columns, callout boxes)
- Timeline or process diagram
- Large number/metric display

### Cognitive load limits

Upper bounds — going under is fine, going over is a defect to redesign:

- **≤ 5 bullets per slide** (see Anti-Patterns #9); past that the audience stops reading and waits for a summary
- **4–5 items per visual group**; the gap *between* groups ≈ 3× the gap *within*, or the grouping does not read
- **≤ 3 font families per deck** — display + body + optional mono; a fourth reads as an accident
- **Headline ≤ 55 characters**; a two-line headline is a smell unless line 2 is a deliberate subhead
- **Line length ≤ 75 characters** in any body text block
- **Chapter break every 7–10 slides** in a long deck — the audience needs a place to exhale

Five-second test: show the slide for five seconds, hide it, ask what was remembered. If it is not the title's claim, the visual hierarchy is wrong.

### Layout Patterns

| Pattern | When to use | Structure |
|---|---|---|
| Title + subtitle | Opening/section breaks | Large title top, subtitle below, minimal |
| Two-column | Comparisons, before/after | Split at 50/50 or 60/40 |
| Three cards | Feature highlights, team | Equal-width rounded rectangles |
| Big number | KPIs, statistics | One huge metric + context below |
| Image + text | Product, case study | Image fills 60%, text in remaining 40% |
| Timeline | Process, history | Horizontal line with milestone points |
| Quote | Testimonial, key insight | Large italic text, attribution below |

### Data Display

- **Charts over tables** — use charts for trends and comparisons; tables only for exact reference data
- **One message per chart** — if a chart tells two stories, split into two charts
- **Summary states conclusions; detail carries the chart** — chart each data series once; a summary or overview slide states its finding in words ("Revenue +44 %, Churn down 0.6 pp"), the following detail slide carries the chart; two slides charting the same numbers is duplication
- **Label directly** — place labels on/near data points, not in a distant legend
- **Consistent scale** — keep y-axis scale consistent across comparable charts
- **Minimal gridlines** — light gray, dotted, only horizontal

### Visual Polish

- **Whitespace** — minimum 0.5" margin from all edges; 0.3" padding inside shapes
- **Alignment** — all elements snap to a consistent grid; misalignment by even 0.1" is visible
- **Shadows** — use sparingly (one shadow style for cards/images, not on every element)
- **Rounded corners** — slight radius (0.1"–0.2") on rectangles for modern feel
- **Consistent spacing** — equal gaps between repeated elements (cards, list items, columns)

## Typography

### Font Pairings

| Heading | Body | Character |
|---|---|---|
| Segoe UI Bold | Segoe UI Light | Professional, Windows-native |
| Arial Black | Arial | Universal fallback |
| Calibri Bold | Calibri | Office-native |
| Montserrat Bold | Open Sans | Modern (requires font install) |

### Size Guidelines

The table below uses the pptxgenjs **LAYOUT_WIDE baseline (960 pt wide / 13.33 × 7.5 in)**. For the **Full HD baseline (1440 × 810 pt / 20 × 11.25 in)**, multiply every size by 1.5.

| Element | LAYOUT_WIDE (960 pt) | Full HD (1440 pt) | Weight |
|---|---|---|---|
| Slide title | 28–36 pt | 42–54 pt | Bold |
| Section header | 22–28 pt | 33–42 pt | Bold |
| Body text | 16–20 pt | 24–30 pt | Regular/Light |
| Captions/labels | 12–14 pt | 18–21 pt | Regular |
| Footnotes | 10–11 pt | 15–17 pt | Light |

### Spacing

- **Line spacing**: 1.2–1.5× for body text
- **Paragraph spacing**: 0.3–0.5× font size between paragraphs
- **Letter spacing**: default (do not tighten or expand unless for large display text)

## Anti-Patterns

Avoid these common mistakes:

1. **Repetitive layouts** — do NOT use the same layout for consecutive slides. Alternate between patterns (text+image, full-bleed, cards, chart, quote).

2. **Centered body text** — body paragraphs should be left-aligned. Center alignment is only for titles, single-line captions, and big numbers.

3. **Text-only slides** — every slide needs a visual anchor. If the content is purely textual, add a relevant shape, icon, or decorative element.

4. **Accent lines/bars for no reason** — decorative lines that don't separate content or indicate hierarchy add noise. Every visual element must serve a purpose.

5. **Too many fonts** — maximum 2 font families per presentation (plus an optional monospace for code or data). Use weight/size for hierarchy, not different fonts.

6. **Gradient overuse** — one gradient per presentation (background or one accent shape). Multiple gradients create visual competition.

7. **Low-contrast text** — gray text on slightly-darker-gray background. Always verify contrast ratio.

8. **Clip art / generic stock** — prefer simple icons (react-icons via SVG export), custom illustrations, or no image over generic stock photos.

9. **Wall of bullets** — more than 5 bullet points means the content should be split across multiple slides or visualized differently.

10. **Inconsistent iconography** — if using icons, use the same icon set throughout. Don't mix outline icons with filled icons.

11. **Callout boxes / shaded note cards** — boxed summaries, accent-bar blocks, shaded text boxes, and similar callout constructions add visual complexity without adding meaning. Use a plain paragraph with an optional bold lead-in instead ("**Note:** …").

## Design Process

### Proactive design alternatives

This applies to full deck creation and design mockups. Single-slide updates and minor edits to an existing deck do not require design variants.

When producing a mockup, new slide deck, or major redesign, include 2–3 thoughtfully chosen design variants without waiting for the user to ask. Each variant should differ in a meaningful way (color palette, layout approach, density level) — not just in font choice or minor spacing.

Present the variants as distinct options with a one-line rationale for each, and let the user select before refining the chosen direction.
