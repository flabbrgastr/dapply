# Resolver must not create performers

The `resolve_nonames_cli.py` resolver is read-assign only: it matches
NO_NAME items against the existing performer set and assigns. It does not
create new performer rows. Performer creation is owned exclusively by the
ingestion path (`dbadd.py`) during the daily scrape.

Decided 2026-07-18 while pulling the LLM call behind the
`PerformerRepository` seam. The earlier inline `INSERT OR IGNORE INTO
performers` blocks inside the resolver's fuzzy/LLM matching were deleted;
the repository interface intentionally exposes no `create_performer`
method, so a future author cannot reintroduce creation from the resolver
without first extending the interface.

This enforces the "zero new performers during clean matching" rule
in one place. Creating performers mid-match was the source of
cascading false positives (a guessed name becomes a real DB row that
then matches other items).
