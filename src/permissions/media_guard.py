"""Project-owned paid-media, domain, budget, and write policies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

from .approval_guard import ApprovalRequired, require_approval


class PolicyDenied(PermissionError):
    """Raised when an operation falls outside the project's permission policy."""


class BudgetExceeded(PolicyDenied):
    """Raised before dispatch when a run or project budget would be exceeded."""


class MissingUnitPrice(ValueError):
    """Raised when planned media has no recorded unit price."""


class CostRecordError(ValueError):
    """Raised when existing cost state is missing or malformed."""


@dataclass(frozen=True)
class UnitPrice:
    provider: str
    unit: str
    usd_per_unit: Decimal

    def __post_init__(self) -> None:
        price = Decimal(str(self.usd_per_unit))
        if not price.is_finite() or price < 0:
            raise ValueError("unit price must be a finite non-negative decimal")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider name is required")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit name is required")
        object.__setattr__(self, "usd_per_unit", price)

    @classmethod
    def create(cls, provider: str, unit: str, usd_per_unit: str | int | float | Decimal) -> "UnitPrice":
        try:
            price = Decimal(str(usd_per_unit))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("unit price must be a non-negative decimal") from exc
        if not price.is_finite() or price < 0:
            raise ValueError("unit price must be a finite non-negative decimal")
        if not provider.strip() or not unit.strip():
            raise ValueError("provider and unit names are required")
        return cls(provider=provider, unit=unit, usd_per_unit=price)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be a finite non-negative decimal")
    return result


def estimate_storyboard_cost(
    storyboard: Mapping[str, Any],
    unit_prices: Mapping[str, UnitPrice],
    *,
    planned_categories: Iterable[str],
    run_budget_usd: str | int | float | Decimal = "25",
    project_actual_usd: str | int | float | Decimal = "0",
    project_budget_usd: str | int | float | Decimal = "300",
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Quote the planned image/video/TTS work, reserving one retry by default.

    Prices are keyed by schema category: image, video, or tts. Image quantity is
    one keyframe per shot; video quantity is one output per shot; TTS quantity
    is narration characters per 1,000-character unit. The caller must name all
    categories it plans to call. No implicit zero price is assigned.
    """

    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots or any(not isinstance(shot, Mapping) for shot in shots):
        raise ValueError("storyboard must contain a non-empty array of shot objects")
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    planned = tuple(dict.fromkeys(planned_categories))
    unknown = set(planned) - {"image", "video", "tts"}
    if unknown:
        raise ValueError(f"unsupported cost categories: {', '.join(sorted(unknown))}")

    quantities = {
        "image": Decimal(len(shots)),
        "video": Decimal(len(shots)),
        "tts": Decimal(sum(len(str(shot.get("narration", ""))) for shot in shots)) / Decimal(1000),
    }
    attempts = Decimal(max_attempts)
    items: list[dict[str, Any]] = []
    estimate = Decimal("0")
    for category in planned:
        quantity = quantities[category]
        if quantity == 0:
            continue
        price = unit_prices.get(category)
        if price is None:
            raise MissingUnitPrice(f"No recorded unit price for planned {category} calls")
        billed_quantity = quantity * attempts
        line_estimate = billed_quantity * price.usd_per_unit
        estimate += line_estimate
        expected_unit = {"image": "keyframe", "video": "shot", "tts": "1000_characters"}[category]
        if price.unit != expected_unit:
            raise MissingUnitPrice(f"{category} price must be recorded per {expected_unit}")
        unit = price.unit
        items.append({
            "category": category,
            "provider": price.provider,
            "unit": unit,
            "quantity": float(billed_quantity),
            "unit_price_usd": _money(price.usd_per_unit),
            "estimated_usd": _money(line_estimate),
            "actual_usd": 0.0,
        })

    run_budget = _decimal(run_budget_usd, "run budget")
    project_actual = _decimal(project_actual_usd, "project actual")
    project_budget = _decimal(project_budget_usd, "project budget")
    if run_budget == 0 or project_budget == 0:
        raise ValueError("run and project budgets must be greater than zero")
    projected_project_total = project_actual + estimate
    if estimate > run_budget:
        raise BudgetExceeded(f"Estimated run cost ${estimate} exceeds the ${run_budget} run budget")
    if projected_project_total > project_budget:
        raise BudgetExceeded(
            f"Projected project cost ${projected_project_total} exceeds the ${project_budget} project budget"
        )

    return {
        "schema_version": "1.0",
        "currency": "USD",
        "run_estimate_usd": _money(estimate),
        "run_actual_usd": 0.0,
        "settled": False,
        "run_budget_usd": _money(run_budget),
        "project_total_usd": _money(projected_project_total),
        "project_budget_usd": _money(project_budget),
        "items": items,
        "tavily_credits": 0.0,
    }


def project_actual_spend(runs_root: Path) -> Decimal:
    """Sum prior run actuals; malformed cost records stop spending fail-closed."""

    total = Decimal("0")
    if not runs_root.exists():
        return total
    for cost_path in runs_root.glob("*/cost.json"):
        try:
            record = json.loads(cost_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise TypeError("cost record must be an object")
            total += _decimal(record["run_actual_usd"], f"{cost_path} run_actual_usd")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CostRecordError(f"Cannot safely read existing cost record: {cost_path}") from exc
    return total



def _committed_amount(record: Mapping[str, Any]) -> Decimal:
    if not isinstance(record, Mapping):
        raise CostRecordError("Cost record must be a JSON object")
    actual = _decimal(record.get("run_actual_usd"), "run actual")
    estimate = _decimal(record.get("run_estimate_usd"), "run estimate")
    if record.get("settled") is True:
        return actual
    if record.get("settled") is not False:
        raise CostRecordError("Cost record must say whether its estimate is settled")
    return max(actual, estimate)


def project_committed_spend(runs_root: Path) -> Decimal:
    """Count actual spend for settled runs and reserve estimates for active runs."""

    total = Decimal("0")
    if not runs_root.exists():
        return total
    for cost_path in runs_root.glob("*/cost.json"):
        try:
            record = json.loads(cost_path.read_text(encoding="utf-8"))
            total += _committed_amount(record)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            raise CostRecordError(f"Cannot safely read existing cost record: {cost_path}") from exc
    return total
def require_allowed_host(url: str, allowed_hosts: Iterable[str]) -> str:
    """Require HTTPS to an exact hostname; reject lookalike suffixes and credentials."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError as exc:
        raise PolicyDenied("Invalid network URL") from exc
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise PolicyDenied("Network requests must use an allowlisted HTTPS host")
    if port not in (None, 443):
        raise PolicyDenied("Non-standard HTTPS ports are not allowed")
    try:
        normalized_host = host.rstrip(".").encode("idna").decode("ascii").lower()
        normalized_allowed = {
            item.rstrip(".").encode("idna").decode("ascii").lower()
            for item in allowed_hosts
        }
    except UnicodeError as exc:
        raise PolicyDenied("Invalid network hostname") from exc
    if normalized_host not in normalized_allowed:
        raise PolicyDenied(f"Network host is not allowlisted: {normalized_host}")
    return normalized_host


def require_allowed_write_path(
    path: Path,
    *,
    workspace_root: Path,
    allow_cast_setup: bool = False,
) -> Path:
    """Resolve and permit runtime writes only beneath runs/ or cast setup assets."""

    root = workspace_root.resolve()
    target = (path if path.is_absolute() else root / path).resolve()
    allowed_roots = [(root / "runs").resolve()]
    if allow_cast_setup:
        allowed_roots.append((root / "assets" / "cast").resolve())
    for allowed_root in allowed_roots:
        if target != allowed_root and allowed_root in target.parents:
            return target
    raise PolicyDenied("Runtime file writes are limited to runs/ and approved assets/cast/ setup")


def write_cost_record(
    record: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Persist a quoted cost record to that run's allowed artifact directory."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise ValueError("invalid run id")
    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "cost.json", workspace_root=workspace_root
    )
    if path.exists():
        raise CostRecordError(f"Refusing to overwrite existing cost record: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def prepare_storyboard_quote(
    storyboard: Mapping[str, Any],
    unit_prices: Mapping[str, UnitPrice],
    *,
    workspace_root: Path,
    run_id: str,
    planned_categories: Iterable[str],
) -> dict[str, Any]:
    """Reserve the final storyboard estimate once, before parallel provider calls."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise ValueError("invalid run id")
    cost_path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "cost.json", workspace_root=workspace_root
    )
    if cost_path.exists():
        raise CostRecordError(f"A cost reservation already exists for run {run_id}")
    quote = estimate_storyboard_cost(
        storyboard,
        unit_prices,
        planned_categories=planned_categories,
        project_actual_usd=project_committed_spend(workspace_root / "runs"),
    )
    write_cost_record(quote, workspace_root=workspace_root, run_id=run_id)
    return quote

def record_actual_cost(
    *,
    workspace_root: Path,
    run_id: str,
    category: str,
    actual_usd: str | int | float | Decimal,
) -> dict[str, Any]:
    """Update a completed provider category and persist actual run/project totals.

    If the provider's billed amount is above the approved estimate or budget,
    the real charge is still recorded before raising, so the next call fails closed.
    """

    actual_increment = _decimal(actual_usd, "actual provider cost")
    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "cost.json", workspace_root=workspace_root
    )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostRecordError(f"Cannot update missing or malformed cost record: {path}") from exc
    if not isinstance(record, dict):
        raise CostRecordError(f"Cost record must be a JSON object: {path}")
    items = record.get("items")
    if not isinstance(items, list):
        raise CostRecordError(f"Cost record has no valid items list: {path}")
    matching = [item for item in items if isinstance(item, dict) and item.get("category") == category]
    if len(matching) != 1:
        raise CostRecordError(f"Expected one cost item for category {category!r}")
    if record.get("settled") is True:
        raise CostRecordError("Cannot add provider cost after this run is settled")
    previous_run_actual = _decimal(record.get("run_actual_usd"), "run actual")
    matching[0]["actual_usd"] = _money(
        _decimal(matching[0].get("actual_usd"), "item actual") + actual_increment
    )
    updated_run_actual = previous_run_actual + actual_increment
    prior_project_total = project_committed_spend(workspace_root / "runs")
    was_settled = record.get("settled") is True
    old_commitment = previous_run_actual if was_settled else max(
        previous_run_actual, _decimal(record.get("run_estimate_usd"), "run estimate")
    )
    new_commitment = updated_run_actual if was_settled else max(
        updated_run_actual, _decimal(record.get("run_estimate_usd"), "run estimate")
    )
    updated_project_total = prior_project_total - old_commitment + new_commitment
    run_budget = _decimal(record.get("run_budget_usd"), "run budget")
    project_budget = _decimal(record.get("project_budget_usd"), "project budget")
    record["run_actual_usd"] = _money(updated_run_actual)
    record["project_total_usd"] = _money(updated_project_total)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if updated_run_actual > _decimal(record.get("run_estimate_usd"), "run estimate"):
        raise BudgetExceeded("Recorded run spend exceeds the approved estimate; stop further calls")
    if updated_run_actual > run_budget:
        raise BudgetExceeded(f"Recorded run spend ${updated_run_actual} exceeds the ${run_budget} run budget")
    if updated_project_total > project_budget:
        raise BudgetExceeded(
            f"Recorded project spend ${updated_project_total} exceeds the ${project_budget} project budget"
        )
    return record

def settle_run_cost(*, workspace_root: Path, run_id: str) -> dict[str, Any]:
    """Release an unused estimate reserve after a run has no more paid work."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "cost.json", workspace_root=workspace_root
    )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostRecordError(f"Cannot settle missing or malformed cost record: {path}") from exc
    if not isinstance(record, dict):
        raise CostRecordError(f"Cost record must be a JSON object: {path}")
    if record.get("settled") is True:
        return record
    old_commitment = _committed_amount(record)
    actual = _decimal(record.get("run_actual_usd"), "run actual")
    total_before = project_committed_spend(workspace_root / "runs")
    projected_actual = total_before - old_commitment + actual
    record["settled"] = True
    record["project_total_usd"] = _money(projected_actual)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    project_budget = _decimal(record.get("project_budget_usd"), "project budget")
    if actual > _decimal(record.get("run_estimate_usd"), "run estimate"):
        raise BudgetExceeded("Settled run spend exceeds the approved estimate")
    if actual > _decimal(record.get("run_budget_usd"), "run budget"):
        raise BudgetExceeded("Settled run spend exceeds the run budget")
    if projected_actual > project_budget:
        raise BudgetExceeded(
            f"Settled project spend ${projected_actual} exceeds the ${project_budget} project budget"
        )
    return record

def guarded_storyboard_call(
    provider: Any,
    *,
    action: str,
    approval_path: Path,
    run_id: str,
    storyboard: Mapping[str, Any],
    unit_prices: Mapping[str, UnitPrice],
    planned_categories: Iterable[str],
    target_url: str,
    allowed_hosts: Iterable[str],
    output_path: Path,
    workspace_root: Path,
    method: str = "generate",
    **kwargs: Any,
) -> Any:
    """Check approval, spend, network host and write target before paid dispatch."""

    approval = require_approval(action=action, approval_path=approval_path, run_id=run_id)
    require_allowed_host(target_url, allowed_hosts)
    safe_output = require_allowed_write_path(output_path, workspace_root=workspace_root)
    run_dir = (workspace_root.resolve() / "runs" / run_id).resolve()
    if safe_output == run_dir or run_dir not in safe_output.parents:
        raise PolicyDenied("Paid provider output must stay inside its own runs/<run-id>/ directory")
    cost_path = (run_dir / "cost.json").resolve()
    existing_record = None
    try:
        if cost_path.is_file():
            existing_record = json.loads(cost_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CostRecordError(f"Cannot safely read current run cost record: {cost_path}") from exc
    if existing_record is None:
        raise CostRecordError("Prepare the approved storyboard cost reservation before paid dispatch")
    if not isinstance(existing_record, dict):
        raise CostRecordError("Current run cost record must be a JSON object")
    if existing_record.get("settled") is True:
        raise PolicyDenied("Cannot dispatch paid work after this run cost is settled")
    current_actual = _decimal(existing_record.get("run_actual_usd"), "current run actual")
    current_estimate = _decimal(existing_record.get("run_estimate_usd"), "current run estimate")
    if current_actual > current_estimate:
        raise BudgetExceeded("Current run spend already exceeds its approved estimate")
    project_actual = project_committed_spend(workspace_root / "runs") - _committed_amount(existing_record)
    record = estimate_storyboard_cost(
        storyboard,
        unit_prices,
        planned_categories=planned_categories,
        project_actual_usd=project_actual,
    )
    try:
        approved_estimate = _decimal(approval["approved_estimate_usd"], "approved estimate")
    except (KeyError, ValueError) as exc:
        raise ApprovalRequired("Approval record must include its approved cost estimate") from exc
    if approved_estimate != Decimal(str(record["run_estimate_usd"])):
        raise ApprovalRequired("Approved cost estimate does not match the current storyboard quote")
    if existing_record is not None:
        current_quote = {
            (item.get("category"), item.get("provider"), item.get("unit"), item.get("quantity"), item.get("unit_price_usd"), item.get("estimated_usd"))
            for item in existing_record.get("items", []) if isinstance(item, dict)
        }
        requested_quote = {
            (item["category"], item["provider"], item["unit"], item["quantity"], item["unit_price_usd"], item["estimated_usd"])
            for item in record["items"]
        }
        if (
            existing_record.get("run_estimate_usd") != record["run_estimate_usd"]
            or current_quote != requested_quote
        ):
            raise ApprovalRequired("Run cost record no longer matches the approved storyboard quote")
    operation: Callable[..., Any] = getattr(provider, method)
    return operation(output_path=safe_output, **kwargs)