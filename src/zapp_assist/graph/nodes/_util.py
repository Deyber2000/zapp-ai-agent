"""Shared helpers and per-language templates for graph nodes.

Nodes are framework-agnostic: no LangGraph, no Anthropic SDK imports here.
"""

from __future__ import annotations

import time
from typing import Any

from ...obs.trace import Span, Trace

# Per-language canned replies. Each is a full, valid sentence in the target language so the contract
# always carries a non-empty reply in `active_lang`.
DECLINE_TEMPLATES = {
    "es": "No puedo confirmar eso con nuestras políticas, así que lo marqué para que lo revise "
    "un compañero.",
    "en": "I can't confirm that from our policies, so I've flagged it for a teammate to review.",
    "pt": "Não posso confirmar isso com nossas políticas, então sinalizei para um colega revisar.",
}
PLACEHOLDER_TEMPLATES = {
    "es": "Esa función aún no está disponible, pero un compañero podrá ayudarte con eso.",
    "en": "That feature isn't available yet, but a teammate will be able to help you with it.",
    "pt": "Esse recurso ainda não está disponível, mas um colega poderá te ajudar com isso.",
}
CLARIFY_TEMPLATES = {
    "es": "¿Puedes aclarar exactamente qué necesitas para poder ayudarte mejor?",
    "en": "Could you clarify exactly what you need so I can help you better?",
    "pt": "Você pode esclarecer exatamente o que precisa para eu te ajudar melhor?",
}
GUARDRAIL_DECLINE_TEMPLATES = {
    "es": "Solo puedo ayudarte con pedidos, entregas y preguntas sobre tu cuenta de Zapp.",
    "en": "I can only help with Zapp orders, deliveries, and account questions.",
    "pt": "Só posso ajudar com pedidos, entregas e perguntas sobre sua conta Zapp.",
}
SAFE_FALLBACK_TEMPLATES = {
    "es": "Lo siento, tuve un problema temporal y no pude completar eso. "
    "Lo marqué para un compañero.",
    "en": "Sorry — I hit a temporary problem and couldn't complete that. "
    "I've flagged it for a teammate.",
    "pt": "Desculpe — tive um problema temporário e não consegui concluir. "
    "Sinalizei para um colega.",
}


def tmpl(templates: dict[str, str], lang: str) -> str:
    return templates.get(lang, templates["en"])


def now() -> float:
    return time.perf_counter()


def add_span(
    trace: Trace,
    node: str,
    start: float,
    status: str = "ok",
    attrs: dict[str, Any] | None = None,
) -> None:
    trace.add_span(
        Span(
            node=node,
            latency_ms=(time.perf_counter() - start) * 1000,
            status=status,  # type: ignore[arg-type]
            attrs=attrs or {},
        )
    )


def last_user_text(user_text: str) -> str:
    return user_text or ""
