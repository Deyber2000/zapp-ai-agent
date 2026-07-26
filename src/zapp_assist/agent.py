"""`Agent.run_turn` — the callable entry point.

Load session → run the graph → save session → return a validated contract.

Dependencies are injected via `Agent.create(...)`, which wires production defaults but lets tests
substitute a mock `LLMClient` (and any other seam) so no test touches the network.
"""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from .config import AppConfig, get_settings, load_config
from .contracts import TurnResult
from .graph.build import build_graph
from .graph.deps import Deps
from .graph.state import TurnState
from .guardrails.baseline import default_registry
from .guardrails.registry import GuardrailRegistry
from .lang.detector import LanguageDetector, LinguaDetector
from .llm.client import LLMClient
from .memory.session_store import InMemorySessionStore, SessionStore
from .obs.trace import Trace
from .rag.store import KB_DIR, BM25Store
from .tools.normalize import register_normalize_tools
from .tools.registry import ToolRegistry


class Agent:
    def __init__(self, deps: Deps, store: SessionStore) -> None:
        self._deps = deps
        self._store = store
        self._graph = build_graph(deps)

    @classmethod
    def create(
        cls,
        *,
        config: AppConfig | None = None,
        llm: LLMClient | None = None,
        store: SessionStore | None = None,
        detector: LanguageDetector | None = None,
        guardrails: GuardrailRegistry | None = None,
        tools: ToolRegistry | None = None,
        rag: BM25Store | None = None,
    ) -> Agent:
        cfg = config or load_config()
        deps = Deps(
            config=cfg,
            llm=llm or _default_llm(cfg),
            detector=detector or LinguaDetector(cfg.languages.supported, cfg.languages.fallback),
            guardrails=guardrails or default_registry(),
            tools=tools or _default_tools(),
            rag=rag or BM25Store.from_kb_dir(KB_DIR, cfg.thresholds.grounding_min_score),
        )
        return cls(deps, store or InMemorySessionStore())

    def run_turn(self, session_id: str, text: str) -> TurnResult:
        t0 = perf_counter()
        session = self._store.load(session_id)
        trace = Trace(turn_id=uuid4().hex, session_id=session_id)
        state = TurnState(
            turn_id=trace.turn_id, session=session, user_text=text or "", trace=trace
        )

        final = self._graph.invoke({"ts": state})
        ts: TurnState = final["ts"]

        result = ts.result or TurnResult.safe_fallback(
            active_lang=self._deps.config.languages.fallback,
            final_normalized_text=text or "",
        )
        ts.trace.total_latency_ms = (perf_counter() - t0) * 1000
        self._store.save(ts.session)
        return result

    @property
    def deps(self) -> Deps:
        return self._deps


def _default_tools() -> ToolRegistry:
    """The production tool registry: signal-fusion normalization (US2), backend actions (US3)."""

    registry = ToolRegistry()
    register_normalize_tools(registry)
    return registry


def _default_llm(cfg: AppConfig) -> LLMClient:
    # Imported lazily so the Anthropic SDK is only required when a real client is actually built
    # (tests inject a mock and never reach here).
    from .llm.anthropic_adapter import AnthropicAdapter

    settings = get_settings()
    return AnthropicAdapter(api_key=settings.anthropic_api_key, config=cfg)
