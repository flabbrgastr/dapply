# ADR-0002: Consolidate performer/RefDB web UI into a single-page app and declutter it

- **Status:** Accepted (2026-07-19)
- **Deciders:** woodmastr, Pi (acting as grilling partner)
- **Supersedes / relates:** ADR-0001 (resolver must not create performers — UI keeps the confirm/merge flow that surfaces unmatched entries)

## Context

`db_viewer.py` served two top-level HTML pages: `templates/viewer.html` (the main
performer/RefDB browser, 1,553 lines, all CSS + JS inline) and `templates/stats.html`
(a separate statistics page, 481 lines). The two shared a dark theme, but `stats.html`
re-declared it inconsistently — its chart card used a light `#f8f9fa` background, which
clashed with the dark palette (a visible theme bug). The single inline `<style>` block
(≈8 KB) was duplicated in spirit across both files and was unmaintainable.

The main page was also cluttered:

- An 11-column performers table mixing high-signal fields (name, rating) with low-signal
  ones (first/last seen, updated) that are useful only in the performer detail view.
- A top KPI bar whose "Avg Rating" was computed **client-side from numeric-only ratings**;
  with an alphabetical-tiered rating scheme (S, A, B, …) that value is ~0 and misleading.
- A top-nav "⚙️ Tags" link that is actually a **resolver-maintenance** feature
  (non-performer blocklist), not a viewer concern — it sat next to core browse navigation.
- A always-visible "🔄 refreshRefDB" button in the main controls, even though refdb refresh
  is only meaningful inside the RefDB browser.

The architecture review (candidate list A/B/C/D) had already pulled all raw SQL into
`PerformerRepository`, introduced the `AnalvidsSource` port, and a `Rating` value object,
so the UI layer could be reshaped freely **without touching any API contract or test**.

## Decision

Lock five scope cuts (each confirmed via grilling interview; all chosen Option A/a):

1. **Single page (D1).** Fold Statistics into the SPA as a section. `GET /stats` now renders
   `viewer.html` (JS auto-shows the Statistics section when the path ends in `/stats`, and a
   `#performer-<id>` hash opens a performer detail). Delete `templates/stats.html`.
2. **Trim the table (D2).** Performers table = 8 columns:
   `Name · AKA · Ref(✓) · Nat · Age · Crawls · Rating · Actions`. First/Last Seen and Updated
   move into the performer detail panel (along with AKA, nationality, age, scene count, tags,
   profile photo, and the item list).
3. **Replace the KPI bar (D3).** Top bar = `Total · Validated · With RefDB · DAP · Unassigned`.
   Drop the broken numeric-only "Avg Rating" entirely (the `Rating` value object owns the
   two-scale model; per-tier distribution is shown on the Statistics page).
4. **Quieten settings (D4).** Move the non-performer-tag blocklist out of the top nav into a
   single quiet "⚙" gear (top-right). Fully functional, just not competing with browse nav.
5. **Localise refdb refresh (D5).** Move "🔄 refdb" into the RefDB section header, next to its
   total count, where its effect is visible.

Cross-cutting: **extract the shared dark theme** to `static/style.css` (linked from
`viewer.html` via `BASE + "/static/style.css"` so it works behind the `/performers` reverse
proxy prefix). This removes the 8 KB inline monolith and kills the `stats.html` light-card
theme clash.

**Explicitly preserved (power features kept):** performer detail view, inline rating edit,
edit/merge + analvids import, item reassign/unassign/delete, confirm-to-refdb, and the full
RefDB browser with filters/pagination. Every REST endpoint and the `/api/*` behaviour are
unchanged, so the 68 existing behaviour tests stay green.

## Consequences

**Good**
- One source of truth for the theme (`static/style.css`); consistency guaranteed.
- Fewer, higher-signal columns; dates surfaced exactly where they're useful (detail view).
- KPI bar tells the truth (no fake average); refdb refresh lives next to its data.
- Resolver-maintenance concern (non-performer tags) no longer pollutes core navigation.
- API contract frozen → 68 tests unaffected.

**Costs / Trade-offs**
- `GET /stats` now returns the full SPA HTML (slightly larger payload than the old thin
  `stats.html`), but the Statistics section is client-rendered from the same `/api/stats` call.
- The `/stats` link in the nav is now a SPA section switch rather than a full page load.

## Implementation notes
- `templates/viewer.html` — rewritten as the single SPA (added `static/style.css` link,
  `stats-section`, trimmed `<thead>`, KPI bar with `kpi-*` ids, gear nav, refdb-header refresh).
- `db_viewer.py::stats_page` → `render_template("viewer.html")`.
- `/api/performers/<id>/features` now also returns `first_seen` / `last_seen` (additive)
  so the detail panel can show them.
- `templates/stats.html` deleted.
- `static/style.css` extracted from the old inline `<style>` (+ `.stats-grid`/`.stat-card`
  rules for the new Statistics section).
