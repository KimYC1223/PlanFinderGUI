from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import DiscoveredPlan


@runtime_checkable
class DisplayInterface(Protocol):
    """Interface between the discovery engine and the UI layer."""

    def log(self, message: str) -> None: ...

    def on_iteration_start(self, iteration: int) -> None: ...

    def on_activity(self, detail: str) -> None:
        """Sync callback called by discover_plan on each tool use."""
        ...

    def on_iteration_cost(self, cost: float, tokens: int, turns: int) -> None: ...

    async def request_approval(
        self, plan: DiscoveredPlan, iteration: int
    ) -> tuple[str, str]:
        """Show plan and await user decision.

        Returns (action, feedback) where action in {'approve', 'reject', 'revise'}.
        """
        ...

    def on_plan_approved(self, plan: DiscoveredPlan, filepath: object) -> None: ...

    def on_plan_rejected(self, plan: DiscoveredPlan, reason: str) -> None: ...

    def on_plan_pending(self, plan: DiscoveredPlan, filepath: object) -> None: ...

    def on_no_more_plans(self) -> None: ...

    def on_session_finished(
        self, approved: int, rejected: int, pending: int
    ) -> None: ...

    def on_error(self, message: str) -> None: ...
