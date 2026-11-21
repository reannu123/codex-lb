from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.usage import metadata_scheduler as scheduler_module
from app.core.usage import pricing_catalog as catalog
from app.core.usage.pricing import ModelPrice

_BUILT_IN_ONLY = "gpt-5.3"
_BUNDLED = "chat-latest"
_BUNDLED_PRICE = ModelPrice(5, 30, 0.5)


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_prices", None)
    monkeypatch.setattr(catalog, "_price_sources", {})


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    async def restore(path: Path) -> None:
        del path

    async def idle(self: scheduler_module.MetadataRefreshScheduler) -> None:
        del self

    monkeypatch.setattr(scheduler_module, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(scheduler_module, "get_codex_version_cache", lambda: SimpleNamespace(restore=restore))
    monkeypatch.setattr(scheduler_module.MetadataRefreshScheduler, "_run_loop", idle)
    return tmp_path


def _write_cache(data_dir: Path, prices: dict[str, ModelPrice], updated_at: str | None = None) -> None:
    snapshot = json.loads(catalog.encode_snapshot(prices))
    if updated_at is not None:
        snapshot["updated_at"] = updated_at
    (data_dir / "pricing-cache.json").write_text(json.dumps(snapshot))


async def _restart() -> None:
    scheduler = scheduler_module.MetadataRefreshScheduler()
    await scheduler.start()
    await scheduler.stop()


def _source_and_price(model: str) -> tuple[str, ModelPrice]:
    return catalog.get_catalog_price_source(model), catalog.get_active_prices()[model]


@pytest.mark.parametrize("cache", [None, "{not json", '{"schema_version": 2, "models": {}}'])
async def test_offline_restart_without_usable_cache_labels_bundled_and_built_in(data_dir: Path, cache) -> None:
    if cache is not None:
        (data_dir / "pricing-cache.json").write_text(cache)
    await _restart()
    assert _source_and_price(_BUNDLED) == ("bundled_snapshot", _BUNDLED_PRICE)
    assert catalog.get_catalog_price_source(_BUILT_IN_ONLY) == "built_in"


async def test_last_good_cache_newer_than_bundle_wins_and_is_labeled(data_dir: Path) -> None:
    cached = ModelPrice(7, 35, 0.7)
    _write_cache(data_dir, {_BUNDLED: cached, "gpt-cache-only": ModelPrice(1, 2)})
    await _restart()
    assert _source_and_price(_BUNDLED) == ("last_good_cache", cached)
    assert _source_and_price("gpt-cache-only") == ("last_good_cache", ModelPrice(1, 2))
    assert catalog.get_catalog_price_source(_BUILT_IN_ONLY) == "built_in"


async def test_newer_bundle_beats_older_cache_but_keeps_cache_only_models(data_dir: Path) -> None:
    _write_cache(
        data_dir,
        {_BUNDLED: ModelPrice(7, 35, 0.7), "gpt-cache-only": ModelPrice(1, 2)},
        updated_at="2020-01-01T00:00:00+00:00",
    )
    await _restart()
    assert _source_and_price(_BUNDLED) == ("bundled_snapshot", _BUNDLED_PRICE)
    assert _source_and_price("gpt-cache-only") == ("last_good_cache", ModelPrice(1, 2))


def test_live_merge_and_partial_refresh_track_per_model_source() -> None:
    live = ModelPrice(6, 31, 0.6)
    catalog.install_prices({_BUNDLED: live})
    assert _source_and_price(_BUNDLED) == ("live_catalog", live)
    assert catalog.get_catalog_price_source(_BUILT_IN_ONLY) == "built_in"
    # A later partial refresh that omits a model keeps its last live price and label.
    catalog.install_prices({"gpt-test": ModelPrice(1, 2)})
    assert _source_and_price(_BUNDLED) == ("live_catalog", live)
    assert _source_and_price("gpt-test") == ("live_catalog", ModelPrice(1, 2))
    assert catalog.get_catalog_price_source("computer-use-preview") == "bundled_snapshot"
