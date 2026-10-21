# SeekMemory plugin view

Install the Release attachment `astrbot_plugin_seekmemory.zip`, reload the plugin,
then open its view from the AstrBot plugin card. A host supporting plugin views
and `astrbot.api.web` is required; host APIs were validated with AstrBot 4.28.1.
Navigation mapping: **Plugin configuration** remains the configuration editor;
the new **Plugin view** contains memory management. AstrBot navigation is unchanged.

The workspace provides all six artifact families, scope/session/state filters,
version comparison, related records, raw evidence, blob hashes and ledger entries.
Edit JSON, scope or active/forgotten state with an audit reason and confirmation.
Every save appends a revision and ledger entry atomically; stale revisions conflict.
Saves use the upstream Artifact kernel and preserve subject IDs and version-level evidence.
New ledger entries store before/after revision numbers; content hashes are in version blobs.
Loading an older payload creates an editable draft, not an immediate rollback.
Merged records cannot be independently restored. Editing does not rebuild graph edges.

Administrators can inspect every scope. `private` uses conversation ownership;
`shared` is visible across conversations; `shadow` enters the same candidate pool
but assembly hides its content. The source-session filter does not change access.
Read-only recall diagnostics accept a UMO, sender ID and query, reuse live rules,
and do not consume designated delivery. Exploration can produce varying results.

Runtime checks cover engine, ledger, journal and provider configuration. Provider
checks do not send model requests. Manual extraction, weekly maintenance and
cancellation share the scheduled-task runner. Editing is blocked during maintenance.
Cancellation preserves unfinished messages but never undoes completed writes;
synchronous weekly work may finish before cancellation is processed. Existing
per-item extraction warnings still require inspection even when a task succeeds.
Extraction resolves the model per session. Four scheduler loops cover nightly extraction,
weekly maintenance, idle extraction and checkpoints. Shutdown awaits tasks, saves pending
messages and flushes recall reinforcement checkpoints before closing the database.

Business logs expose severity, stage, module, relative file, function, line,
duration, explicit scalar context and exception frame locations. Filters compose
across kind, status, severity, module and text. Extraction stages include provider
calls, parsing, deduplication, validation, persistence and impression revision.
Task IDs propagate through ContextVar; stage completion does not finish a task.
Legacy entries show an unknown source; exception text and locals are omitted.
Lifecycle logs retain 500 events in memory and rotate at 1 MiB with one backup.
They record task states, IDs, counters and error types, not chat/model content.
Retained unfinished tasks are marked interrupted after restart. Active tasks poll
every two seconds; refresh idle views manually. This is not a complete host log archive.

For standalone development, run `pnpm dev` in `dashboard/`. Mock mutations are
temporary, tasks are simulated, and mock diagnostics only approximate text matching.
Production uses the host bridge and never falls back to mock data. See the
[engineering guide](../../dashboard/README.md) and [Chinese guide](../zh/webui.md).

Screenshots use fictional mock data and the shared production components:

![Memory library](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/webui-memory.png)
![Runtime and tasks](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/webui-runtime.png)
![Lifecycle logs](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/webui-logs.png)

Preview images live on the separate [webui-previews branch](https://github.com/SXP-Simon/SeekMemory/tree/webui-previews),
not in the code PR or release ZIP. The [25-image gallery](https://github.com/SXP-Simon/SeekMemory/tree/webui-previews#readme)
covers all nine category filters, versions, evidence, ledger, tasks, diagnostics
and structured logs. Categories share the same library/detail UI; they are not
nine specialized editors. Mock diagnostics do not verify real recall quality.

![Recall diagnostics](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/diagnostics-result.png)
![No-match diagnostics](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/diagnostics-empty.png)
