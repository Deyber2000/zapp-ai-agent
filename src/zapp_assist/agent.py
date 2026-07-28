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
from .guardrails.semantic import LLMSemanticClassifier
from .lang.detector import LanguageDetector, LinguaDetector
from .llm.client import LLMClient
from .memory.session_store import InMemorySessionStore, SessionStore
from .obs.log import get_logger
from .obs.trace import Trace
from .rag.retriever import Retriever, build_retriever
from .tools.mock_backend import MockBackend, register_backend_tools
from .tools.normalize import register_normalize_tools
from .tools.registry import ToolRegistry

_log = get_logger("zapp.turn")


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
        rag: Retriever | None = None,
    ) -> Agent:
        cfg = config or load_config()
        resolved_llm = llm or _default_llm(cfg)
        semantic = LLMSemanticClassifier(resolved_llm, cfg)  # off unless config enables it
        deps = Deps(
            config=cfg,
            llm=resolved_llm,
            detector=detector or LinguaDetector(cfg.languages.supported, cfg.languages.fallback),
            guardrails=guardrails or default_registry(cfg, semantic),
            tools=tools or _default_tools(),
            rag=rag or build_retriever(cfg, resolved_llm, get_settings().openai_api_key),
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

        # One structured line per turn: enough to debug and cost-account it from logs alone (XI).
        _log.info(
            "turn_complete",
            turn_id=ts.trace.turn_id,
            session_id=session_id,
            intent=ts.intent,
            active_lang=result.active_lang,
            detected_lang=result.detected_lang,
            lang_confidence=round(result.lang_confidence, 3),
            confidence=round(result.confidence_score, 3),
            needs_review=result.needs_review,
            degraded=ts.degraded,
            blocked=ts.blocked,
            guardrails_in=[d.action for d in result.guardrails.input],
            guardrails_out=[d.action for d in result.guardrails.output],
            spans=len(ts.trace.spans),
            input_tokens=ts.trace.tokens.input,
            output_tokens=ts.trace.tokens.output,
            cost_usd=round(ts.trace.cost_usd, 6),
            latency_ms=round(ts.trace.total_latency_ms, 2),
        )
        return result

    @property
    def deps(self) -> Deps:
        return self._deps


def _default_tools() -> ToolRegistry:
    """The production tool registry: signal-fusion normalization (US2), backend actions (US3)."""

    registry = ToolRegistry()
    register_normalize_tools(registry)
    register_backend_tools(registry, MockBackend())
    return registry


def _default_llm(cfg: AppConfig) -> LLMClient:
    # Imported lazily so only the CHOSEN vendor SDK is required when a real client is built (tests
    # inject a mock and never reach here). `config.provider` selects the adapter — the whole point
    # of the `LLMClient` seam (Constitution V).
    settings = get_settings()
    if cfg.provider == "openai":
        from .llm.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(api_key=settings.openai_api_key, config=cfg)

    from .llm.anthropic_adapter import AnthropicAdapter

    return AnthropicAdapter(api_key=settings.anthropic_api_key, config=cfg)
