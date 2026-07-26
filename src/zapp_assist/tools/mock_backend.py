"""Deterministic mock order/account backend (US3, spec scope decision).

Stands in for real order systems: an in-memory order book with `lookup_order`,
`reschedule_delivery`, and `cancel_order`. State-changing operations are IDEMPOTENT (re-applying the
same change is a no-op) and bump a `state_changes` counter for observability. Execute-at-most-once
(FR-013/SC-005) is enforced at the node/session layer via `PendingAction.status`; the idempotent
backend is defense-in-depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from .registry import ToolRegistry, ToolResult

# Operations that change backend state and therefore require explicit HITL confirmation.
STATE_CHANGING = frozenset({"reschedule_delivery", "cancel_order"})


@dataclass
class _Order:
    id: str
    status: str  # scheduled | rescheduled | cancelled
    window: str


@dataclass
class MockBackend:
    """A tiny deterministic order book. Seeded with a couple of orders for the demo/eval."""

    orders: dict[str, _Order] = field(
        default_factory=lambda: {
            "A1001": _Order("A1001", "scheduled", "Sat 14:00–16:00"),
            "A1002": _Order("A1002", "scheduled", "Sun 09:00–11:00"),
        }
    )
    state_changes: int = 0

    def lookup(self, order_id: str) -> _Order | None:
        return self.orders.get(order_id)

    def reschedule(self, order_id: str, new_time: str) -> ToolResult:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        if order.status == "cancelled":
            return ToolResult(ok=False, error="order_cancelled")
        if order.status == "rescheduled" and order.window == new_time:
            return ToolResult(  # idempotent: already at this window
                ok=True, data={"order_id": order_id, "window": new_time, "idempotent": True}
            )
        order.window, order.status = new_time, "rescheduled"
        self.state_changes += 1
        return ToolResult(ok=True, data={"order_id": order_id, "window": new_time})

    def cancel(self, order_id: str) -> ToolResult:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        if order.status == "cancelled":
            return ToolResult(ok=True, data={"order_id": order_id, "idempotent": True})
        order.status = "cancelled"
        self.state_changes += 1
        return ToolResult(ok=True, data={"order_id": order_id, "status": "cancelled"})


class LookupOrderArgs(BaseModel):
    order_id: str


class RescheduleArgs(BaseModel):
    order_id: str
    new_time: str


class CancelArgs(BaseModel):
    order_id: str


@dataclass
class _LookupOrderTool:
    backend: MockBackend
    name: str = "lookup_order"
    description: str = "Look up an order's current status and delivery window (read-only)."
    input_schema: type[BaseModel] = LookupOrderArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, LookupOrderArgs)
        order = self.backend.lookup(args.order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        return ToolResult(
            ok=True, data={"order_id": order.id, "status": order.status, "window": order.window}
        )


@dataclass
class _RescheduleTool:
    backend: MockBackend
    name: str = "reschedule_delivery"
    description: str = "Reschedule an order's delivery to a new time (state-changing)."
    input_schema: type[BaseModel] = RescheduleArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, RescheduleArgs)
        return self.backend.reschedule(args.order_id, args.new_time)


@dataclass
class _CancelTool:
    backend: MockBackend
    name: str = "cancel_order"
    description: str = "Cancel an order (state-changing)."
    input_schema: type[BaseModel] = CancelArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CancelArgs)
        return self.backend.cancel(args.order_id)


def register_backend_tools(registry: ToolRegistry, backend: MockBackend) -> None:
    """Register the US3 order-action tools, all sharing one backend instance."""

    registry.register(_LookupOrderTool(backend))
    registry.register(_RescheduleTool(backend))
    registry.register(_CancelTool(backend))
