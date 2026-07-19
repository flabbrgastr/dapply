# CONTEXT — Domain Model

Shared language for the dapply project. Read this before renaming things or
proposing seams; the architecture review (`/improve-codebase-architecture`)
assumes these terms exist.

## Core entities

- **Performer** — a person in the database. Unique `name`; carries `urls`
  (pipe-separated), a `crawls` counter, `aka` (alternate spellings), a `rating`,
  a `validated` flag, `first_seen` / `last_seen`, and a `refdb_status`.
- **Item** — a single scene/video post. Belongs to one performer (or
  `NO_NAME`). Carries `item_url`, `title`, `item_date`, `hits`, `source_file`,
  and `thumbnail_url`.
- **NO_NAME** — sentinel performer for items whose performer could not be
  determined during scraping. The resolver tries to reassign these.
- **RefDB model** — a verified model profile scraped from analvids.com
  (`refdb_models`). The source of truth used to **confirm/validate** performers.
  `refdb_validated_tags` records manually confirmed tags.
- **Scene** — a scene record (`performer_scenes`) linking an item to
  co-performers; used for co-performer analysis.
- **Profile image** — a cached webp thumbnail of a refdb model
  (`performer_images`), stored locally after an analvids lookup.

## Performer attributes (vocabulary)

- **AKA** — alternate spellings of a performer name, accumulated when fuzzy
  matching merges near-miss spellings (e.g. `Mia Kalany` → AKA of `Mia Kalani`).
- **Validated** — flag that a performer is a real, confirmed model. Set when an
  item title starts with `Model:`, when confirmed via the web UI, or when the
  name matches a refdb model.
- **Crawl** — one scrape run. The `crawls` counter increments per *new* URL
  found for a performer (re-seen URLs don't count).
- **Rating** — a quality score. Either an **alphabetical tier** (`AAA`…`E`, each
  with optional `+`/`-`) or a **numeric** value (`0`–`10`). Modeled as the
  `Rating` value object in `rating.py` (parse + sort key + category +
  comparison); `build_stats_payload` sorts/categorizes through it. The legacy
  `viewer_rendering` helpers were folded into this module.
- **RefDB status** — per-performer match against `refdb_models`: `matched`
  (exact name) or `fuzzy` (near, via rapidfuzz). Computed in batch.
- **DAP** — "double anal" tag on `performer_features`; used for DAP counts.

## Architectural seam

- **PerformerRepository** — the single **port** for all performer-database
  operations. Two adapters satisfy it:
  - `SqlitePerformerRepository` — production, backed by `performers.db`.
  - `InMemoryPerformerRepository` — tests, backed by dicts.
- The webapp (`db_viewer.py` + `viewer_queries.py`) talks to the database
  **only** through this port; it is built by `db_viewer.create_app(repo=None)`,
  which injects the repository (defaults to `SqlitePerformerRepository`). That
  injection is what makes the webapp testable with `InMemoryPerformerRepository`
  through the Flask test client.
- **ADR-0001** — the resolver must **not** create performers; performer
  creation is owned by the `dbadd` ingestion path and the web UI's confirm
  action. The repository port is the only writer.
- **AnalvidsSource** — the external analvids.com lookup port
  (`analvids_source.py`). `ScrapingAnalvidsSource` (HTTP + PIL) is the
  production adapter; `FakeAnalvidsSource` is the test double. It is **pure
  with respect to the database** (reads/writes only the cached image on the
  filesystem); the calling route composes it with the repository port. Both
  ports are injected into the webapp via `db_viewer.create_app(repo, analvids)`.

## Web interface (single-page app)

- `db_viewer.py` is a Flask app whose **only** rendered HTML page is
  `templates/viewer.html` — a single-page app with sections switched by JS
  (Performers · RefDB · Unassigned · Statistics). `GET /stats` renders the same
  `viewer.html` and the JS auto-shows the Statistics section; a `#performer-<id>`
  hash opens a performer detail. `templates/stats.html` was deleted.
- The shared dark theme lives in `static/style.css` (linked via
  `BASE + "/static/style.css"` so it works behind the `/performers` reverse-proxy
  prefix). All data comes from the `/api/*` JSON endpoints; no page renders
  server-side data beyond the shell.
- **ADR-0002** — the UI was consolidated into this SPA and decluttered
  (8-column performer table, truthful KPI bar, settings gear, localised
  refdb refresh). The route/API contract is frozen; all behaviour tests pass.
