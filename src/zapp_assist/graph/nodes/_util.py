"""Shared helpers and per-language templates for graph nodes.

Nodes are framework-agnostic: no LangGraph, no Anthropic SDK imports here.
"""

from __future__ import annotations

import time
from typing import Any

from ...memory.session_store import Session
from ...obs.trace import Span, Trace

# Per-language canned replies. Each is a full, valid sentence in the target language so the contract
# always carries a non-empty reply in `active_lang`.
DECLINE_TEMPLATES = {
    "es": "No puedo confirmar eso con nuestras políticas, así que lo marqué para que lo revise "
    "un compañero.",
    "en": "I can't confirm that from our policies, so I've flagged it for a teammate to review.",
    "pt": "Não posso confirmar isso com nossas políticas, então sinalizei para um colega revisar.",
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
# Courtesy / greetings / meta — acknowledged warmly and redirected (NOT refused as out-of-scope).
SMALLTALK_TEMPLATES = {
    "es": "¡Con gusto! Estoy aquí para ayudarte con tus pedidos, entregas y cuenta de Zapp. "
    "¿En qué más puedo ayudarte?",
    "en": "Glad to help! I'm here for your Zapp orders, deliveries, and account — "
    "what else can I do for you?",
    "pt": "Com prazer! Estou aqui para ajudar com seus pedidos, entregas e conta Zapp. "
    "Em que mais posso ajudar?",
}
# Shown instead of re-emitting the exact previous reply (e.g. re-running a completed onboarding).
REPETITION_TEMPLATES = {
    "es": "Ya está todo listo con eso. ¿Hay algo más en lo que pueda ayudarte?",
    "en": "You're all set there — is there anything else I can help you with?",
    "pt": "Está tudo certo com isso. Posso ajudar com mais alguma coisa?",
}
SAFE_FALLBACK_TEMPLATES = {
    "es": "Lo siento, tuve un problema temporal y no pude completar eso. "
    "Lo marqué para un compañero.",
    "en": "Sorry — I hit a temporary problem and couldn't complete that. "
    "I've flagged it for a teammate.",
    "pt": "Desculpe — tive um problema temporário e não consegui concluir. "
    "Sinalizei para um colega.",
}
# Onboarding slot-fill prompts — ask for ONE missing field at a time, never fabricate the rest.
ONBOARDING_ASK_NAME = {
    "es": "¡Claro! Para completar tu registro, ¿cuál es tu nombre completo?",
    "en": "Sure! To finish setting up your account, what's your full name?",
    "pt": "Claro! Para concluir seu cadastro, qual é o seu nome completo?",
}
ONBOARDING_ASK_PHONE = {
    "es": "Gracias. ¿Cuál es tu número de teléfono (con el código de tu país)?",
    "en": "Thanks. What's your phone number (including your country code)?",
    "pt": "Obrigado. Qual é o seu número de telefone (com o código do seu país)?",
}
# Confirmations — `{name}` / `{phone}` are filled by the onboarding node.
ONBOARDING_CONFIRM = {
    "es": "¡Listo, {name}! Registré tu número como {phone}. ¿Es correcto?",
    "en": "All set, {name}! I saved your number as {phone}. Is that correct?",
    "pt": "Tudo certo, {name}! Salvei seu número como {phone}. Está correto?",
}
ONBOARDING_UNVERIFIED = {
    "es": "Gracias, {name}. No pude validar el número «{phone}», así que lo marqué "
    "para que un compañero lo revise.",
    "en": "Thanks, {name}. I couldn't validate the number “{phone}”, so I've flagged it "
    "for a teammate to review.",
    "pt": "Obrigado, {name}. Não consegui validar o número “{phone}”, então sinalizei "
    "para um colega revisar.",
}


# Fail-safe when the reply cannot be produced in the active language after one correction (002).
LANG_MISMATCH_TEMPLATES = {
    "es": "Lo siento, tuve problemas para responder en tu idioma, así que lo marqué para que lo "
    "revise un compañero.",
    "en": "Sorry — I had trouble replying in your language, so I've flagged this for a teammate "
    "to review.",
    "pt": "Desculpe — tive dificuldade para responder no seu idioma, então sinalizei para um "
    "colega revisar.",
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


def recent_history(session: Session, limit: int = 3) -> str:
    """Compact recent-turn context for history-aware routing/action (oldest to newest, or '').

    Each line is the user's message + how it was routed + a short assistant reply, so a follow-up
    that supplies what the assistant just asked for (e.g. an order number after a cancel request) is
    understood as continuing that thread rather than being classified on its bare text.
    """

    turns = session.history[-limit:]
    if not turns:
        return ""
    lines = []
    for turn in turns:
        intent = f" [{turn.intent}]" if turn.intent else ""
        reply = turn.reply if len(turn.reply) <= 120 else turn.reply[:117] + "..."
        lines.append(f"- user: {turn.user_text}{intent}\n  assistant: {reply}")
    return "Recent conversation (oldest to newest):\n" + "\n".join(lines)
