# adapters: AstrBot Host Integration

## Responsibility

adapters translates AstrBot events, providers, and message sending into application ports. Host objects do not leak into core, recall, or app/runtime domain policies.

## Composition root

On start, AstrBotPlugin builds Store, Cache, Tree, Graph, HybridRetriever, Source-backed Buffer, CheckpointManager, application services, AgentRuntime, Jobs, WebRoutes, and background services. On stop, it stops background and management tasks, unregisters its own routes, saves the buffer, flushes checkpoints, and finally closes Store.

main.py defines the plugin entry point and delegates lifecycle; composition and wiring live in adapters/astrbot_plugin.py. AstrBotHooks in adapters/astrbot_hooks.py maps host hooks to service calls: access decisions, input acceptance, memory injection, assistant-reply capture, post-send delivery recording, and runtime/tool observation. It does not implement extraction, capacity, or maintenance algorithms.

## Port adapters

- AstrBotRuntimeAdapter converts host messages into RuntimeInput and manages event-extra values for user/reply Source IDs, turn IDs, final recall IDs, and episode deduplication.
- AstrBotModelGateway provides ModelGateway for deferred replies.
- AstrBotActionPort provides MessageSender.
- ProviderChatModel wraps a host extraction/persona provider as ChatModel.
- SeekMemoryContextAdapter connects Runtime's MemoryContextPort to the existing RecallService.

AstrBot centralizes time conversion in utc8_time_hook in astrbot_time.py. User messages, normal replies, deferred replies, and runtime audit pass through this adapter hook before calling the existing RunRecorder. New timestamps use ISO strings with an explicit +08:00 offset; kernel read views retain the existing naive format. Fields, kernel interfaces, and database structure are unchanged.

AstrBotBuffer reuses Buffer admission and topic algorithms, while AstrBotSourceView reuses SourceStore queries. Both use the same hook for pending projections and recovered processed parents. Historical Sources are not rewritten. Offset-aware legacy values are converted; missing, invalid, and offset-free values are preserved without guessing the old machine's timezone or deriving absolute event time or queue age from them. Whether those old values were wrong, or derived memories need revision, requires a separate audit against the original environment.

Runtime decisions still use epoch timestamps independently of the OS timezone. Time adaptation does not change core, Buffer, extraction contracts, or nightly-maintenance scheduling configuration.

AccessService uses full session UMO, sender ID, owner/trusted configuration, and observe_groups to decide whether a message can be observed/recalled. Host event details are normalized only at this boundary; plugin composition owns config and database path.

## Current boundaries

Hook registration must use the real plugin module path, so callbacks stay discoverable after reload. Runtime tool filtering runs before a model request; a tool observation hook after invocation is not enforcement. Host API limitations and plugin startup failures are handled at the outer boundary and must not leak AstrBot dependencies into business modules.
