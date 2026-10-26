# Changelog and compatibility

## Changelog

- Add new release notes to the root `CHANGELOG.md` in Simplified Chinese and English with equivalent meaning.
- Put unreleased work under `Unreleased`; do not rewrite published history unless the Lead asks.
- Describe user-visible behavior and compatibility impact. Keep the two language sections aligned in meaning; literal translation is not required.

## Persisted data and public configuration

If a change can affect data or configuration already on disk, stop before implementation. Explain the current format, affected users and rollback consequences, then present viable strategies: preserve compatibility, migrate, or make an explicitly breaking/reset change. Breaking changes are allowed when chosen explicitly; there is no default compatibility strategy. Wait for the Lead to choose; do not silently select one.

If a change does not affect persisted data or public configuration, state that explicitly. Do not add Artifact fields without an issue and Lead decision; do not silently change schema or public config keys. State assumptions when other requirements are ambiguous, and record the chosen decision, migration/reset path and release notes when applicable.
