# Layer 5 — Observability

← [Layer 4 · Guardrails & security](layer-4-guardrails.md)  ·  [All six layers](architecture.md#the-six-layers)  ·  [Layer 6 · Evaluation](layer-6-evaluation.md) →

---

> One `Span` per node, token/cost/latency accounting per turn, feeding the eval suite.
> [src/zapp_assist/obs/trace.py](../src/zapp_assist/obs/trace.py)

```mermaid
flowchart TB
    subgraph turn["One turn"]
        N1["guardrail_in<br/>decisions · blocked · semantic_degraded"]
        N2["detect_language<br/>detected · active · confidence · switched · pending"]
        N3["route_intent<br/>intent · confidence"]
        N4["support_rag<br/>grounded · hits · top_score"]
        N5["verify_reply_language<br/>reply_lang · reply_match · corrected"]
        N6["verify_confidence<br/>score · needs_review"]
        N7["guardrail_out<br/>decisions · sem_degraded"]
        N8["assemble<br/>needs_review · fallback"]
    end

    N1 --> TR
    N2 --> TR
    N3 --> TR
    N4 --> TR
    N5 --> TR
    N6 --> TR
    N7 --> TR
    N8 --> TR

    ADP["LLM adapter<br/>usage in / out / cache-read tokens"] -->|record_llm| TR
    ADP --> COST["compute_cost from the config pricing table<br/>attributed to the model that actually ran"]
    COST --> TR
    RET["AdvancedRetriever<br/>expansion, self-query, rerank calls"] -->|"on_llm callback — so retrieval spend<br/>cannot hide outside the turn budget"| TR

    TR["<b>Trace</b><br/>turn_id · session_id<br/>ordered spans with status ok / error / skipped<br/>TokenTotals · cost_usd · total_latency_ms"]

    TR --> C1["<b>consumer 1 — the eval suite</b><br/>latency percentiles, cost per conversation,<br/>language fidelity from reply_match,<br/>guardrail category and layer counts"]
    TR --> C2["<b>consumer 2 — logs</b><br/>one structured line per turn<br/>emitted from run_turn via structlog<br/>ids · language · intent · tokens · cost · latency"]
    TR -.-> C3["<b>consumer 3 — an exporter</b><br/>NOT IMPLEMENTED<br/>OTel / Langfuse would map from here"]

    RT["Agent.run_turn builds the Trace,<br/>sets total_latency_ms,<br/>emits one structured turn log,<br/>then returns TurnResult"]
    RT -.-> TR
    EV["the eval works around this by driving<br/>the compiled graph directly<br/>instead of calling run_turn"]
    EV -.-> C1

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef llm fill:#dbeafe,stroke:#2563eb,color:#0c1d51;
    classDef gap fill:#f1f5f9,stroke:#94a3b8,color:#0f172a,stroke-dasharray: 5 4;
    class N1,N2,N3,N4,N5,N6,N7,N8,TR,COST,C1,EV det;
    class ADP,RET llm;
    class C2,C3,RT gap;
```

**This is the one layer where the diagram is more honest than the code.** Capture is complete and
well-designed — every node, every token, every cost, including retrieval-side spend that would
otherwise be invisible. Emission does not exist: three dashed boxes, and the only working consumer
reaches the trace by bypassing the public entry point.

## What is captured

A `Trace` per turn carries `turn_id`, `session_id`, an ordered span list, `TokenTotals`
(input/output/cache-read), cumulative `cost_usd`, and `total_latency_ms`
([trace.py:35-52](../src/zapp_assist/obs/trace.py#L35-L52)). Each node appends exactly one span with its
name, latency, status (`ok` | `error` | `skipped`), and free-form attributes — and the attributes are
chosen to answer the questions you actually ask during an incident:

| Node | Attributes | Answers |
|---|---|---|
| `guardrail_in` | `decisions`, `blocked`, `semantic_degraded` | why was this refused; was safety checking complete |
| `detect_language` | `detected`, `active`, `confidence`, `switched`, `pending` | why did it answer in that language |
| `route_intent` | `intent`, `confidence` | why did it take that branch |
| `support_rag` | `grounded`, `hits`, `top_score` | did it have grounding, and how strong |
| `verify_reply_language` | `reply_lang`, `reply_match`, `corrected` | did the language guarantee hold |
| `verify_confidence` | `score`, `needs_review` | why was this escalated |
| `assemble` | `needs_review`, `fallback` | was this a real answer or a degradation |

Cost is computed from the config pricing table at the adapter boundary
([trace.py:55-61](../src/zapp_assist/obs/trace.py#L55-L61)), so it is attributed to the model that
actually ran — including retrieval-side expansion calls, which report usage back through an `on_llm`
callback so they land in the *turn's* budget rather than vanishing
([advanced.py:171-172](../src/zapp_assist/rag/advanced.py#L171-L172),
[support_rag.py:63](../src/zapp_assist/graph/nodes/support_rag.py#L63)). That detail matters: retrieval
enhancements are the easiest place for LLM spend to hide.

## Decision: signals ride in the trace, not the contract

`reply_match`, guardrail layer/category counts, and per-signal confidences are span attributes, not
`TurnResult` fields. The contract is frozen (`extra="forbid"`) and is a *caller* interface; these are
*operator* signals. Adding them to the contract would couple every consumer to internal diagnostics
and break the schema for a signal only evaluation needs. The eval consumes the trace directly — which
is what the trace was designed for — and reads fidelity out of it without ever inspecting reply text
([trace.py:73-89](../src/zapp_assist/obs/trace.py#L73-L89)).

## Decision: a hand-rolled `Trace` instead of OpenTelemetry

The `Trace`/`Span` shape is deliberately OTel-compatible in spirit (named spans, latency, status,
attribute bags) without the dependency. At this scope OTel would add a collector, an exporter, and
configuration surface to produce data that currently has no consumer other than the in-repo eval.
The abstraction is small enough that an exporter is a mapping function, not a migration.

**This is the right call *given* an export path exists. It does not, yet — see below.**

## Gap: the trace summary is emitted; a full-trace export path is not

The layer's original weakest point — *nothing was emitted* — is now closed; what remains is an
export path:

- `structlog` is wired up: `Agent.run_turn` emits **one structured line per turn** (`turn_complete`)
  carrying the ids, language, intent, review flag, guardrail actions, span count, tokens, cost, and
  latency ([agent.py](../src/zapp_assist/agent.py), [obs/log.py](../src/zapp_assist/obs/log.py)). So
  the constitution's standard — "debuggable from logs alone" — **is met for a running agent**: the
  per-turn summary is enough to trace and cost-account a turn from logs.
- What is *not* yet exported is the **full `Trace` object** (the ordered per-span detail). The log
  line is a summary; the complete span tree still falls out of scope after the turn, and the eval is
  the only consumer that reads it in full — by driving the compiled graph directly to keep the trace
  ([evals/runner.py:43-52](../evals/runner.py#L43-L52)).

**Remaining fix, in order of cost:** (1) ~~emit one structured log line per turn~~ — **done**;
(2) return the trace alongside the result, or accept an optional sink callback, so callers can route
the full span tree; (3) add an OTel exporter behind the same
sink. Step 1 has closed the gap between the claim and the code; steps 2–3 deepen it.

---

---

← [Layer 4 · Guardrails & security](layer-4-guardrails.md)  ·  [All six layers](architecture.md#the-six-layers)  ·  [Layer 6 · Evaluation](layer-6-evaluation.md) →

Wider context: [system flow across all layers](system-flow.md)  ·  [design stance and known gaps](architecture.md)
