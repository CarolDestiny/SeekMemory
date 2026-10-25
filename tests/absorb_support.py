"""Test-only adapter that exercises the production IngestService extraction path."""

from __future__ import annotations

from contextlib import nullcontext

from services.ingest_service import IngestService


class _Logger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


async def _provider_for(_session_id):
    return None


async def absorb(
    items,
    artifacts,
    sources,
    cache,
    graph,
    model,
    log=lambda _msg: None,
    owner_id: str = "",
    *,
    strict: bool = False,
    stage=lambda _name: nullcontext(),
):
    service = IngestService(
        buffer=None,
        artifacts=artifacts,
        sources=sources,
        extraction=None,
        cache=cache,
        graph=graph,
        journal=None,
        config=lambda _key, default: default,
        provider_for=_provider_for,
        owner_id=lambda: owner_id,
        logger=_Logger(),
    )
    return await service.extract(
        items,
        model,
        log=log,
        strict=strict,
        stage=stage,
    )
