"""Safe MarketTrim deletion extension for the canonical writer.

The public command remains ``UPSERT_MODEL_BUNDLE`` so deletion travels through
exactly the same CanonicalInputPipeline, revision log, outbox, Git commit and
release publication path as every other admin vehicle edit.  A delete intent is
an explicit ``payload.delete_trim = {canonical_id: ...}`` marker.

Why an extension instead of a second writer: the existing bundle writer owns
the catalogue JSON layout and the input pipeline already supplies atomic staged
writes.  This module only replaces the bundle mutation for that one explicit
marker; ordinary UPSERT_MODEL_BUNDLE commands still execute the original method
unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
import json
from pathlib import Path
from typing import Any

from . import canonical_write as cw


def _campaign_reference(data_dir: Path, year: int, trim_id: str) -> str | None:
    """Return a campaign file still naming the trim, if one exists."""
    root = data_dir / str(year) / "market" / "campaigns"
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Broken evidence is not a reason to guess that deletion is safe.
            raise cw.CanonicalWriteError(f"cannot verify campaign references in {path}")
        if trim_id in json.dumps(payload, ensure_ascii=False, sort_keys=True):
            return str(path)
    return None


def _delete_trim_bundle(self: cw.CanonicalWritePipeline,
                        command: cw.CanonicalWriteCommand,
                        request: Any):
    if not isinstance(request, dict):
        raise cw.CanonicalWriteError("delete_trim must be an object")
    trim_id = str(request.get("canonical_id") or "").strip()
    if not trim_id:
        raise cw.CanonicalWriteError("delete_trim.canonical_id is required")

    model_id = command.canonical_id or str(command.payload.get("model", {}).get("canonical_id") or "")
    if not model_id:
        raise cw.CanonicalWriteError("trim deletion requires the parent model canonical_id")

    # Resolve against the catalogue before mutating anything.  This proves the
    # submitted trim really belongs to the submitted model and gives us the
    # canonical generation id rather than trusting form data for identity.
    catalog = self._catalog(command.year)
    trim = catalog.trims.get(trim_id)
    if trim is None:
        raise cw.CanonicalWriteError(f"unknown MarketTrim {trim_id!r}")
    if trim.model_id != model_id:
        raise cw.CanonicalWriteError("MarketTrim does not belong to the submitted model")

    # A trim with facts attached is not a disposable identity.  Refuse the
    # delete instead of leaving price/spec files pointing at an id the next
    # release no longer contains.  Registration references live in Supabase
    # and are checked by the admin server action before this command is queued.
    prices = cw.PriceLedger.load(self.data_dir, year=command.year, catalog=catalog)
    if prices.records_for(trim_id, include_retracted=True):
        raise cw.CanonicalWriteError(
            f"cannot delete MarketTrim {trim_id!r}: price history still references it")
    if self._facts_by_trim(command.year).get(trim_id):
        raise cw.CanonicalWriteError(
            f"cannot delete MarketTrim {trim_id!r}: comparable-spec facts still reference it")
    campaign_path = _campaign_reference(Path(self.data_dir), command.year, trim_id)
    if campaign_path:
        raise cw.CanonicalWriteError(
            f"cannot delete MarketTrim {trim_id!r}: campaign data still references it ({campaign_path})")

    brand_id, local_model_id = cw._model_raw_id(model_id)
    payloads = cw._load_brand_payloads(self.data_dir, command.year)
    brand_payload = payloads.get(brand_id)
    if not brand_payload:
        raise cw.CanonicalWriteError(f"unknown brand {brand_id!r}")
    model = cw._find_model_raw(brand_payload, local_model_id)
    if model is None:
        raise cw.CanonicalWriteError(f"unknown model {model_id!r}")

    generation_id = trim.generation_id
    generation = cw._find_generation_raw(model, generation_id, model_id)
    if generation is None:
        raise cw.CanonicalWriteError(
            f"MarketTrim {trim_id!r} points to unknown generation {generation_id!r}")

    raw_trims = generation.get("trims")
    if not isinstance(raw_trims, list):
        raise cw.CanonicalWriteError("generation.trims is not an array")

    delete_index: int | None = None
    for index, raw in enumerate(raw_trims):
        if not isinstance(raw, dict):
            continue
        candidate = cw.trim_identity(
            generation_id, raw.get("id"), raw.get("name", ""), raw.get("powertrain", ""))
        if candidate == trim_id:
            if delete_index is not None:
                raise cw.CanonicalWriteError(
                    f"MarketTrim {trim_id!r} appears more than once in canonical source")
            delete_index = index
    if delete_index is None:
        raise cw.CanonicalWriteError(
            f"MarketTrim {trim_id!r} exists in Catalog but not in its canonical source row")

    before = cw.to_jsonable(trim)
    del raw_trims[delete_index]

    # Validate the whole catalogue before the real tree changes.  If deleting
    # the row would violate any catalogue invariant, nothing is written.
    validated = cw._validate_payloads(payloads, command.year)
    if trim_id in validated.trims:
        raise cw.CanonicalWriteError("trim deletion validation still found the target MarketTrim")

    target = cw.year_dir(self.data_dir, command.year) / f"{brand_id}.json"
    cw._atomic_json(target, brand_payload)
    self._forget_catalog(command.year)
    return "catalog", "market_trim", trim_id, before, None, (str(target),)


def install_trim_delete_extension() -> None:
    """Install once for every normal ``vehreg`` package import."""
    cls = cw.CanonicalWritePipeline
    if getattr(cls, "_tdr_trim_delete_installed", False):
        return

    original = cls._upsert_model_bundle

    @wraps(original)
    def wrapped(self: cw.CanonicalWritePipeline, command: cw.CanonicalWriteCommand):
        request = command.payload.get("delete_trim")
        if request is None:
            return original(self, command)
        return _delete_trim_bundle(self, command, request)

    cls._upsert_model_bundle = wrapped
    cls._tdr_trim_delete_installed = True


__all__ = ["install_trim_delete_extension"]
