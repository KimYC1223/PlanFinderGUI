from __future__ import annotations

import asyncio

from PySide6.QtCore import QObject, Signal

from ..engine.models import DiscoveredPlan


class GuiDisplayAdapter(QObject):
    """Bridges the async engine and the Qt UI via signals + asyncio.Future."""

    log_message = Signal(str)
    activity_updated = Signal(str)
    iteration_started = Signal(int)
    cost_updated = Signal(float, int, int)          # cost, tokens, turns
    plan_ready = Signal(object, int)                # (DiscoveredPlan, iteration)
    plan_approved = Signal(object, str)             # (plan, filepath_str)
    plan_rejected = Signal(object, str)             # (plan, reason)
    plan_pending = Signal(object, str)              # (plan, filepath_str)
    no_more_plans = Signal()
    session_finished = Signal(int, int, int)        # approved, rejected, pending
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._approval_future: asyncio.Future | None = None

    # --- DisplayInterface sync methods ---

    def log(self, message: str) -> None:
        self.log_message.emit(message)

    def on_activity(self, detail: str) -> None:
        self.activity_updated.emit(detail)

    def on_iteration_start(self, iteration: int) -> None:
        self.iteration_started.emit(iteration)

    def on_iteration_cost(self, cost: float, tokens: int, turns: int) -> None:
        self.cost_updated.emit(cost, tokens, turns)

    def on_plan_approved(self, plan: DiscoveredPlan, filepath: object) -> None:
        self.plan_approved.emit(plan, str(filepath))

    def on_plan_rejected(self, plan: DiscoveredPlan, reason: str) -> None:
        self.plan_rejected.emit(plan, reason or "")

    def on_plan_pending(self, plan: DiscoveredPlan, filepath: object) -> None:
        self.plan_pending.emit(plan, str(filepath))

    def on_no_more_plans(self) -> None:
        self.no_more_plans.emit()

    def on_session_finished(self, approved: int, rejected: int, pending: int) -> None:
        self.session_finished.emit(approved, rejected, pending)

    def on_error(self, message: str) -> None:
        self.error_occurred.emit(message)

    # --- Async approval mechanism ---

    async def request_approval(
        self, plan: DiscoveredPlan, iteration: int
    ) -> tuple[str, str]:
        """Emit plan_ready signal and await user button click.

        The engine coroutine suspends here. When the user clicks
        Approve/Reject/Revise, submit_approval() resolves the future and
        the engine resumes.
        """
        loop = asyncio.get_running_loop()
        self._approval_future = loop.create_future()
        self.plan_ready.emit(plan, iteration)
        result = await self._approval_future
        self._approval_future = None
        return result  # ('approve'/'reject'/'revise', feedback_str)

    def submit_approval(self, action: str, feedback: str = "") -> None:
        """Called by Qt button click handlers to resume the engine."""
        if self._approval_future and not self._approval_future.done():
            self._approval_future.set_result((action, feedback))

    def cancel_pending(self) -> None:
        """Called when Stop is clicked while awaiting user approval."""
        if self._approval_future and not self._approval_future.done():
            self._approval_future.cancel()
