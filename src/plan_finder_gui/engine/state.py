from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .fileutil import atomic_write
from .models import DiscoveredPlan, PlanFinderState, RejectionRecord


class StateManager:
    """Manages rejection state stored as .state.json inside the report dir."""

    def __init__(self, report_dir: Path) -> None:
        self.path = report_dir / ".state.json"
        self._state: PlanFinderState | None = None
        self.load_error: bool = False

    def load(self) -> PlanFinderState:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._state = PlanFinderState.model_validate(data)
            except Exception:
                import shutil
                backup = self.path.with_suffix(
                    f".json.corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                shutil.copy2(self.path, backup)
                self._state = PlanFinderState()
                self.load_error = True
        else:
            self._state = PlanFinderState()
        return self._state

    def save(self) -> None:
        if self._state is None:
            return
        self._state.last_run = datetime.now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, self._state.model_dump_json(indent=2))

    @property
    def state(self) -> PlanFinderState:
        if self._state is None:
            return self.load()
        return self._state

    def add_rejection(self, plan: DiscoveredPlan, reason: str = "") -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason=reason,
        )
        self.state.rejected_plans.append(record)
        self.state.total_rejected += 1
        self.save()

    def add_pending(self, plan: DiscoveredPlan) -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason="(pending review)",
        )
        self.state.rejected_plans.append(record)
        self.save()

    def record_approval(self, plan: DiscoveredPlan) -> None:
        record = RejectionRecord(
            title=plan.title,
            category=plan.category.value,
            description_summary=plan.description[:200],
            rejected_at=datetime.now(),
            reason="(approved)",
        )
        self.state.rejected_plans.append(record)
        self.state.total_approved += 1
        self.save()

    def clear_rejections(self) -> None:
        self.state.rejected_plans.clear()
        self.save()
