"""Deterministic mock order/account/membership backend (US3, spec scope decision).

Stands in for real backends: an in-memory order book plus a demo account + membership. Read-only
lookups (`lookup_order`, `track_order`) and state-changing ops that mirror the KB domains —
`reschedule_delivery`, `cancel_order`, `process_refund`, `start_return`, `update_contact`,
`cancel_membership`. State changes are IDEMPOTENT (re-applying is a no-op) and bump `state_changes`
for observability. Execute-at-most-once (FR-013/SC-005) is enforced at the session layer via
`PendingAction.status`; the idempotent backend is defense-in-depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from .registry import ToolRegistry, ToolResult

# Action categories — the single source of truth the planner/executor branch on.
READ_ONLY = frozenset({"lookup_order", "track_order"})
ORDER_ACTIONS = frozenset({"reschedule_delivery", "cancel_order", "process_refund", "start_return"})
ACCOUNT_ACTIONS = frozenset({"update_contact", "cancel_membership"})
ORDER_CENTRIC = READ_ONLY | ORDER_ACTIONS  # require a valid order_id (existence-checked)
STATE_CHANGING = ORDER_ACTIONS | ACCOUNT_ACTIONS  # require HITL confirmation before executing

CONTACT_FIELDS = frozenset({"email", "phone"})


@dataclass
class _Order:
    id: str
    status: str  # scheduled | rescheduled | cancelled | refunded | return_started
    window: str


@dataclass
class _Account:
    email: str = "user@example.com"
    phone: str = "+520000000000"
    membership_active: bool = True


@dataclass
class MockBackend:
    """A tiny deterministic backend. Seeded with orders + one account for the demo/eval."""

    orders: dict[str, _Order] = field(
        default_factory=lambda: {
            "A1001": _Order("A1001", "scheduled", "Sat 14:00–16:00"),
            "A1002": _Order("A1002", "scheduled", "Sun 09:00–11:00"),
        }
    )
    account: _Account = field(default_factory=_Account)
    state_changes: int = 0

    def lookup(self, order_id: str) -> _Order | None:
        return self.orders.get(order_id)

    def track(self, order_id: str) -> ToolResult:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        stage = {
            "scheduled": "preparing your order",
            "rescheduled": "preparing your order",
            "cancelled": "order cancelled",
            "refunded": "refunded",
            "return_started": "return in progress",
        }.get(order.status, "in progress")
        return ToolResult(
            ok=True, data={"order_id": order_id, "stage": stage, "window": order.window}
        )

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

    def refund(self, order_id: str) -> ToolResult:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        if order.status == "refunded":
            return ToolResult(ok=True, data={"order_id": order_id, "idempotent": True})
        order.status = "refunded"
        self.state_changes += 1
        return ToolResult(ok=True, data={"order_id": order_id, "status": "refunded"})

    def start_return(self, order_id: str) -> ToolResult:
        order = self.orders.get(order_id)
        if order is None:
            return ToolResult(ok=False, error="order_not_found")
        if order.status == "return_started":
            return ToolResult(ok=True, data={"order_id": order_id, "idempotent": True})
        order.status = "return_started"
        self.state_changes += 1
        return ToolResult(ok=True, data={"order_id": order_id, "status": "return_started"})

    def update_contact(self, contact_field: str, value: str) -> ToolResult:
        if contact_field not in CONTACT_FIELDS:
            return ToolResult(ok=False, error="unsupported_field")
        if getattr(self.account, contact_field) == value:
            return ToolResult(
                ok=True, data={"field": contact_field, "value": value, "idempotent": True}
            )
        setattr(self.account, contact_field, value)
        self.state_changes += 1
        return ToolResult(ok=True, data={"field": contact_field, "value": value})

    def cancel_membership(self) -> ToolResult:
        if not self.account.membership_active:
            return ToolResult(ok=True, data={"membership_active": False, "idempotent": True})
        self.account.membership_active = False
        self.state_changes += 1
        return ToolResult(ok=True, data={"membership_active": False})


class LookupOrderArgs(BaseModel):
    order_id: str


class TrackArgs(BaseModel):
    order_id: str


class RescheduleArgs(BaseModel):
    order_id: str
    new_time: str


class CancelArgs(BaseModel):
    order_id: str


class RefundArgs(BaseModel):
    order_id: str


class StartReturnArgs(BaseModel):
    order_id: str


class UpdateContactArgs(BaseModel):
    field: str
    value: str


class CancelMembershipArgs(BaseModel):
    pass


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
class _TrackOrderTool:
    backend: MockBackend
    name: str = "track_order"
    description: str = "Track an order's delivery progress (read-only)."
    input_schema: type[BaseModel] = TrackArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, TrackArgs)
        return self.backend.track(args.order_id)


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


@dataclass
class _RefundTool:
    backend: MockBackend
    name: str = "process_refund"
    description: str = "Refund an order to the original payment method (state-changing)."
    input_schema: type[BaseModel] = RefundArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, RefundArgs)
        return self.backend.refund(args.order_id)


@dataclass
class _StartReturnTool:
    backend: MockBackend
    name: str = "start_return"
    description: str = "Start a return for an order (state-changing)."
    input_schema: type[BaseModel] = StartReturnArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, StartReturnArgs)
        return self.backend.start_return(args.order_id)


@dataclass
class _UpdateContactTool:
    backend: MockBackend
    name: str = "update_contact"
    description: str = "Update the account's email or phone (state-changing)."
    input_schema: type[BaseModel] = UpdateContactArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, UpdateContactArgs)
        return self.backend.update_contact(args.field, args.value)


@dataclass
class _CancelMembershipTool:
    backend: MockBackend
    name: str = "cancel_membership"
    description: str = "Cancel the Zapp+ membership (state-changing)."
    input_schema: type[BaseModel] = CancelMembershipArgs

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CancelMembershipArgs)
        return self.backend.cancel_membership()


def register_backend_tools(registry: ToolRegistry, backend: MockBackend) -> None:
    """Register the US3 order/account/membership action tools, all sharing one backend instance."""

    registry.register(_LookupOrderTool(backend))
    registry.register(_TrackOrderTool(backend))
    registry.register(_RescheduleTool(backend))
    registry.register(_CancelTool(backend))
    registry.register(_RefundTool(backend))
    registry.register(_StartReturnTool(backend))
    registry.register(_UpdateContactTool(backend))
    registry.register(_CancelMembershipTool(backend))
