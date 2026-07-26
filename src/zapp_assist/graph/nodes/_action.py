"""Shared helpers for the action (HITL) nodes: confirmation parsing + per-language restatement.

Confirmation is DETERMINISTIC by design (Constitution X/VIII): an irreversible action executes
only on an explicit affirmative, never on a model's guess. An unclear reply keeps the action
pending and re-asks; a clear negative abandons it. Safety-critical, so no LLM is consulted.
"""

from __future__ import annotations

import re
from typing import Literal

Confirmation = Literal["confirm", "decline", "ambiguous"]

_AFFIRM = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|confirm(?:ed)?|go\s+ahead|do\s+it|please\s+do|correct"
    r"|s[ií]|claro|correcto|confirmo|adelante|hazlo|de\s+acuerdo"
    r"|sim|pode|isso|confirmar)\b",
    re.IGNORECASE,
)
_NEGATE = re.compile(
    r"\b(no|nope|don'?t|do\s+not|cancel\s+that|stop|wait|nevermind|never\s+mind|not\s+now"
    r"|mejor\s+no|no\s+gracias|detente|cancela"
    r"|n[ãa]o|melhor\s+n[ãa]o|pare)\b",
    re.IGNORECASE,
)
# Hedges that must read as ambiguous even though they contain an affirmative token (e.g. "not sure"
# contains "sure"). Checked first so an unclear answer can never be mistaken for a "yes".
_UNSURE = re.compile(
    r"\b(not\s+sure|unsure|maybe|no\s+estoy\s+segur\w*|tal\s+vez|quiz[aá]s?"
    r"|n[ãa]o\s+tenho\s+certeza|talvez)\b",
    re.IGNORECASE,
)


def classify_confirmation(text: str) -> Confirmation:
    """Deterministic yes/no reading of a confirmation reply. Ambiguity never executes."""

    body = text or ""
    if _UNSURE.search(body):
        return "ambiguous"
    affirm = bool(_AFFIRM.search(body))
    negate = bool(_NEGATE.search(body))
    if affirm and not negate:
        return "confirm"
    if negate and not affirm:
        return "decline"
    return "ambiguous"


def summarize_action(action: str, params: dict, lang: str) -> str:
    """A short human restatement of the action, in the active language (for confirm/done/re-ask)."""

    order = params.get("order_id", "")
    if action == "cancel_order":
        return {
            "es": f"cancelar el pedido {order}",
            "en": f"cancel order {order}",
            "pt": f"cancelar o pedido {order}",
        }.get(lang, f"cancel order {order}")
    if action == "reschedule_delivery":
        when = params.get("new_time", "")
        return {
            "es": f"reprogramar la entrega del pedido {order} para {when}",
            "en": f"reschedule delivery for order {order} to {when}",
            "pt": f"reagendar a entrega do pedido {order} para {when}",
        }.get(lang, f"reschedule delivery for order {order} to {when}")
    generic = {"es": "realizar esa acción", "en": "perform that action", "pt": "realizar essa ação"}
    return generic.get(lang, "perform that action")


# `{x}` placeholders are filled by the action nodes.
ACTION_ASK_ORDER = {
    "es": "Con gusto. ¿Cuál es el número de tu pedido?",
    "en": "Happy to help. What's your order number?",
    "pt": "Com prazer. Qual é o número do seu pedido?",
}
ACTION_ASK_TIME = {
    "es": "¿Para qué horario quieres reprogramar la entrega?",
    "en": "What time would you like to reschedule the delivery to?",
    "pt": "Para que horário você quer reagendar a entrega?",
}
ACTION_UNSUPPORTED = {
    "es": "No puedo realizar esa acción todavía, pero un compañero podrá ayudarte.",
    "en": "I can't perform that action yet, but a teammate will be able to help you.",
    "pt": "Ainda não posso realizar essa ação, mas um colega poderá te ajudar.",
}
ACTION_NOT_FOUND = {
    "es": "No encontré el pedido {order}. ¿Puedes verificar el número?",
    "en": "I couldn't find order {order}. Could you double-check the number?",
    "pt": "Não encontrei o pedido {order}. Você pode verificar o número?",
}
ACTION_LOOKUP = {
    "es": "El pedido {order} está «{status}» con entrega {window}.",
    "en": "Order {order} is “{status}” with delivery {window}.",
    "pt": "O pedido {order} está “{status}” com entrega {window}.",
}
ACTION_CONFIRM = {
    "es": "Voy a {summary}. ¿Lo confirmas? (sí/no)",
    "en": "I'm about to {summary}. Do you confirm? (yes/no)",
    "pt": "Vou {summary}. Você confirma? (sim/não)",
}
ACTION_REASK = {
    "es": "Solo para confirmar: ¿quieres que proceda a {summary}? Responde sí o no.",
    "en": "Just to confirm: do you want me to {summary}? Please reply yes or no.",
    "pt": "Só para confirmar: você quer que eu {summary}? Responda sim ou não.",
}
ACTION_DONE = {
    "es": "Listo. Completé: {summary}.",
    "en": "Done. I've completed: {summary}.",
    "pt": "Pronto. Concluí: {summary}.",
}
ACTION_FAILED = {
    "es": "No pude completar {summary}. Lo marqué para que un compañero lo revise.",
    "en": "I couldn't complete {summary}. I've flagged it for a teammate to review.",
    "pt": "Não consegui concluir {summary}. Sinalizei para um colega revisar.",
}
ACTION_ABANDONED = {
    "es": "De acuerdo, no haré ningún cambio. ¿Hay algo más en que pueda ayudarte?",
    "en": "Okay, I won't make any changes. Is there anything else I can help with?",
    "pt": "Certo, não farei nenhuma alteração. Posso ajudar com mais alguma coisa?",
}
