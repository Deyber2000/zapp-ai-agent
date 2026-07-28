# Zapp Assist — System Flow

How the whole system fits together, end to end. [architecture.md](architecture.md) goes *down* into
each of the six layers and argues the trade-offs; this document goes *across* them — what runs when,
what data moves between the parts, what happens when something breaks, and which module is allowed to
import what.

Six views, each answering one question:

| # | View | Question it answers |
|---|---|---|
| 1 | [Three time domains](#1-three-time-domains) | What runs at build time, at serving time, and at verification time? |
| 2 | [One request, every component](#2-one-request-every-component) | What exactly happens between a user message and a returned contract? |
| 3 | [Artifact flow](#3-artifact-flow) | Which files exist, who writes them, who reads them? |
| 4 | [The degradation map](#4-the-degradation-map) | Every way this can fail, and where each failure lands |
| 5 | [State lifetimes](#5-state-lifetimes) | What survives a turn, what survives a session, what is thrown away |
| 6 | [The seam map](#6-the-seam-map) | Which module may import which dependency, and why it matters |

Colours are the same throughout the docs: **green** = deterministic/offline, **blue** = spends an LLM
call, **red** = fail-safe path, **dashed grey** = not implemented.

---

## 1. Three time domains

The system runs in three distinct phases that never overlap. The only things crossing between them
are committed files — which is what makes each phase independently reproducible.

```mermaid
flowchart TB
    subgraph BUILD["BUILD TIME — run by a human, occasionally"]
        direction TB
        B1["author or edit a KB document"]
        B1 --> B2["zapp-ingest validate<br/>schema · language · duplication · coverage"]
        B2 --> B3["zapp-ingest build<br/>chunk + resolve HyPE questions from cache"]
        B3 --> B4["zapp-ingest build --refresh<br/>ONLY when a doc has no cache entry<br/>the single step that needs an API key"]
        B3 --> BA[("committed KB + enrichment cache")]
        B4 --> BA
    end

    subgraph SERVE["SERVING TIME — run per user message"]
        direction TB
        S0["Agent.create — once per process<br/>load config + secrets, pick the provider adapter,<br/>build BM25 index, embed the KB, compile the graph"]
        S0 --> S1["Agent.run_turn — once per message<br/>load session, run the 12-node graph,<br/>save session, return the contract"]
        S1 --> SA[("TurnResult — always schema-valid")]
        S1 --> SB[("Trace — spans, tokens, cost, latency")]
    end

    subgraph VERIFY["VERIFICATION TIME — run by CI and by a reviewer"]
        direction TB
        V1["uv run pytest — 207 tests, keyless"]
        V2["ruff + mypy"]
        V3["zapp-ingest validate — KB gate"]
        V4["zapp-eval<br/>deterministic core always runs;<br/>live LLM-judged tier when a key exists"]
        V4 --> VA[("report.json + report.md — committed")]
        VA --> V5["drift guard test<br/>fresh run must match the committed report"]
    end

    BA ==>|"read at Agent.create — never regenerated on the serving path"| S0
    SB ==>|"the eval reads spans for latency, cost, language fidelity"| V4
    SA ==>|"the eval scores the contract against labels"| V4
    V5 -.->|"a drift failure sends you back to the KB or the code"| BUILD

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef llm fill:#dbeafe,stroke:#2563eb,color:#0c1d51;
    class B1,B2,B3,BA,S1,SA,SB,V1,V2,V3,VA,V5 det;
    class B4,S0,V4 llm;
```

**The rule this encodes:** anything expensive, non-deterministic, or key-dependent is pushed left,
into build time, where it is paid once and committed. The serving path inherits the *result* of that
work, not the work. Verification runs entirely on committed artifacts, with no network.

`Agent.create` is blue because it embeds the knowledge base when a key is present — the one place
serving-time setup spends money. `zapp-eval` is blue only for its optional live tier.

---

## 2. One request, every component

A single support question, from CLI to contract. Every arrow is real control flow.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant C as CLI
    participant A as Agent
    participant St as SessionStore
    participant G as Graph
    participant N as Nodes
    participant L as LLM adapter
    participant R as Retriever
    participant T as Trace

    Note over C,R: Agent.create — once per process
    C->>A: Agent.create
    A->>A: load config.yaml and .env, both lru-cached
    A->>L: build the adapter selected by config.provider
    A->>R: BM25 index over 42 docs, embed 210 representations if a key exists
    A->>G: build_graph deps — the only LangGraph call in the codebase

    Note over U,T: run_turn — once per message
    U->>C: hasta cuando puedo reprogramar mi entrega
    C->>A: run_turn session_id, text
    A->>St: load session_id
    St-->>A: deep copy of Session — active_lang, slots, pending_action
    A->>T: new Trace with a fresh turn_id
    A->>G: invoke with the whole TurnState in one channel

    G->>N: guardrail_in
    N->>T: span — 4 regex rules, no rule fired
    G->>N: detect_language
    N->>L: language second opinion
    L-->>N: LangSignal es 0.96
    N->>N: lingua wins, LLM only adjusts confidence, lock active_lang
    N->>T: span + token usage and cost
    G->>N: route_intent
    N->>L: intent classification
    L-->>N: support 0.95
    N->>T: span
    G->>N: support_rag
    N->>R: search
    R->>R: BM25 union dense, RRF-fused, trimmed to top_k
    R-->>N: ranked documents with scores
    N->>L: answer strictly from these snippets
    L-->>N: GroundedAnswer with a grounded flag
    N->>T: span — grounded, hits, top_score
    G->>N: verify_reply_language
    N->>N: lingua on the reply — matches, no LLM spent
    N->>T: span — reply_match true
    G->>N: verify_confidence
    N->>T: span — combined score vs threshold
    G->>N: guardrail_out
    N->>T: span — 3 output rules, none fired
    G->>N: assemble
    N->>N: build and validate TurnResult, or substitute safe_fallback
    N->>T: span
    G-->>A: final state

    A->>T: set total_latency_ms
    A->>St: save the mutated Session
    A-->>C: TurnResult
    C-->>U: reply, in Spanish
    Note over A,T: a structured summary line is logged; the full Trace is not returned — see gap 2
```

Three details in that sequence are load-bearing:

- **The session is exchanged as a deep copy** in both directions, so a turn that crashes mid-flight
  leaves the stored session exactly as it was.
- **`assemble` runs last and unconditionally.** Whatever happened upstream, the final step either
  validates a contract or substitutes one that cannot fail validation.
- **A per-turn summary is logged; the full trace is not exported.** Step-by-step capture works and a
  structured line is emitted from `run_turn`; the complete span tree is not yet returned or exported.

---

## 3. Artifact flow

Every file the system reads or writes, and the direction it moves.

```mermaid
flowchart LR
    subgraph inputs["Committed inputs — reviewable, diffable"]
        KB[("rag/kb/*.json<br/>42 documents")]
        EC[("ingestion/enrichment_cache.json<br/>42 content-addressed entries")]
        CFG[("config.yaml<br/>provider · models · effort<br/>7 thresholds · pricing<br/>guardrail policy · retrieval toggles")]
        DSET[("evals/dataset/*.json<br/>20 labelled cases")]
        ETH[("evals/eval_config.yaml<br/>10 thresholds")]
    end

    subgraph secrets["Environment — never committed"]
        ENV[/".env — ANTHROPIC_API_KEY, OPENAI_API_KEY<br/>git-ignored, documented by .env.example"/]
    end

    subgraph runtime["Runtime objects — in memory only"]
        AC["AppConfig — typed, lru-cached"]
        SET["Settings — typed, lru-cached"]
        IDX["BM25 index + dense matrix"]
        SESS["Session — active_lang, slots, pending_action"]
        TRC["Trace — spans, tokens, cost, latency"]
        RES["TurnResult — the contract"]
    end

    subgraph outputs["Generated, committed outputs"]
        RPT[("evals/report.json<br/>evals/report.md")]
    end

    EC -->|"build time only"| KB
    KB --> IDX
    CFG --> AC
    ENV --> SET
    AC --> IDX
    SET -->|"decides whether dense retrieval is even possible"| IDX

    IDX --> RES
    AC --> RES
    SESS <-->|"load then save, deep-copied both ways"| RES
    RES --> TRC

    DSET --> RPT
    ETH --> RPT
    RES --> RPT
    TRC --> RPT
    RPT -->|"asserted byte-stable by the drift guard test"| DSET

    TRC -->|"one structured line per turn from run_turn; full-trace exporter not yet"| LOGS[("structured logs")]

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef gap fill:#f1f5f9,stroke:#94a3b8,color:#0f172a,stroke-dasharray: 5 4;
    class KB,EC,CFG,DSET,ETH,AC,SET,IDX,SESS,TRC,RES,RPT det;
    class LOGS gap;
    class ENV det;
```

Two properties worth stating: **no secret ever reaches a committed file** (the only path out of
`.env` is into an in-memory `Settings`), and **every committed output is regenerable from committed
inputs** with no network — which is exactly what the drift-guard test asserts.

---

## 4. The degradation map

Every failure mode in the system, and where each one lands. This is the single most important
property of the design: **every arrow terminates in a valid contract.**

```mermaid
flowchart LR
    subgraph fails["Failure sources"]
        F1["provider timeout, rate limit,<br/>connection error, 5xx, 400"]
        F2["structured output will not parse"]
        F3["model returns stop_reason refusal"]
        F4["no embedding key, or the embedding call errors"]
        F5["a node raises an unexpected exception"]
        F6["a tool returns ok=false<br/>e.g. order not found"]
        F7["semantic guardrail classifier degrades"]
        F8["a retrieval enhancement stage degrades"]
        F9["nothing clears the grounding threshold"]
        F10["reply is in the wrong language<br/>and the one correction fails"]
        F11["user writes an unsupported language"]
        F12["assemble itself raises"]
    end

    F1 --> H1["LLMResult degraded=true<br/>never raised to the caller"]
    F2 --> H2["ONE bounded repair re-ask"]
    H2 -->|"still unparseable"| H1
    H2 -->|"parsed"| GOOD
    F3 --> H1
    F4 --> H4["DenseRetriever disabled<br/>hybrid returns the sparse hits"]
    F5 --> H5["wrapper catches it<br/>degraded=true + an error span"]
    F6 --> H6["honest message — I could not find that order<br/>+ needs_review"]
    F7 --> H7["zero decisions returned<br/>degrade to the regex layer, never fail open"]
    F8 --> H8["the stage becomes a no-op<br/>base retrieval result stands"]
    F9 --> H9["decline template<br/>+ needs_review, no model call"]
    F10 --> H10["safe in-language template<br/>+ needs_review"]
    F11 --> H11["reply in the fallback language<br/>+ needs_review, no lock, no switch"]
    F12 --> H12["TurnResult.safe_fallback<br/>built from clamped primitives"]

    H1 --> ROUTE{"which node<br/>asked?"}
    ROUTE -->|"detect_language"| KEEP["keep the deterministic detection<br/>the turn is NOT degraded for a missing second opinion"]
    ROUTE -->|"route_intent, onboarding, action_plan"| DEG["mark the turn degraded<br/>downstream nodes are skipped"]
    ROUTE -->|"support_rag"| H9
    ROUTE -->|"verify_reply_language"| H10

    H4 --> BM["BM25 floor — still grounds, still declines correctly"]
    H8 --> BM

    KEEP --> ASM
    DEG --> ASM
    BM --> GOOD
    H5 --> ASM
    H6 --> ASM
    H7 --> RVW["needs_review = true"]
    H9 --> ASM
    H10 --> ASM
    H11 --> ASM
    RVW --> ASM
    GOOD["normal path"] --> ASM

    ASM["assemble — runs on EVERY path, including degraded"]
    ASM --> NOREPLY{"is there a<br/>usable reply?"}
    NOREPLY -->|no| H12
    NOREPLY -->|yes| VALID
    H12 --> VALID(["<b>valid TurnResult</b><br/>schema-checked, non-empty reply,<br/>needs_review=true on every degraded path"])

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef safe fill:#fee2e2,stroke:#dc2626,color:#450a0a;
    class H2,H4,H8,BM,GOOD,ASM,KEEP det;
    class H1,H5,H6,H7,H9,H10,H11,H12,DEG,RVW,VALID safe;
```

Read it as a claim you can falsify: **there is no path from any box on the left to a crash, a hang, a
partial object, or a schema-invalid response.** The cost of that guarantee is a bias toward
over-flagging — the system would rather escalate a good turn to a human than quietly return a bad
one, which is the correct direction for a support agent.

Note the one asymmetry: a degraded *language second opinion* does **not** degrade the turn. The
deterministic detector is authoritative anyway, so losing the cross-check costs confidence, not
correctness.

---

## 5. State lifetimes

Three kinds of state with three different lifetimes. Confusing them is how agent systems leak.

```mermaid
flowchart TB
    subgraph perturn["Per turn — created and discarded"]
        TS["<b>TurnState</b><br/>user_text · language · intent · normalization<br/>retrieval · confidence · draft_reply · result<br/>blocked · degraded · needs_review_override<br/>reply_lang · reply_match · reply_corrected"]
        TR["<b>Trace</b><br/>spans · tokens · cost · latency"]
    end

    subgraph persession["Per session — survives across turns"]
        SE["<b>Session</b><br/>active_lang — locked language<br/>pending_switch_lang + pending_switch_count<br/>slots — full_name, phone with canonical + valid<br/>pending_action — name, params, status<br/>history — bounded recent turns"]
    end

    subgraph perprocess["Per process — built once, immutable"]
        DP["<b>Deps</b><br/>config · llm · detector<br/>guardrails · tools · rag"]
        GR["compiled graph"]
        IX["BM25 index + dense matrix"]
    end

    START(["turn begins"]) --> LOADS["store.load — returns a DEEP COPY"]
    LOADS --> TS
    TS -->|"nodes read and write it"| TS
    TS -->|"nodes read only"| DP
    TS --> TR
    TS -->|"the same Session object is mutated in place"| SE
    TS --> DONE["turn ends"]
    DONE --> SAVES["store.save — stores a DEEP COPY"]
    SAVES --> SE
    DONE -->|"discarded"| TSX["TurnState is garbage"]
    DONE -.->|"currently also discarded — gap 2"| TRX["Trace is garbage"]

    DP --- GR
    DP --- IX

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef gap fill:#f1f5f9,stroke:#94a3b8,color:#0f172a,stroke-dasharray: 5 4;
    class TS,TR,SE,DP,GR,IX,LOADS,SAVES,START,DONE,TSX det;
    class TRX gap;
```

The deep copy on both `load` and `save` is what makes the store swappable: nothing in a node holds a
reference into stored state, so replacing the in-memory dict with Redis changes no node. It is also
what makes a crashed turn harmless — the stored session was never touched.

The one thing that *should* outlive the turn and does not is the `Trace`. Everything else has the
lifetime it should.

---

## 6. The seam map

Which module may import what. Arrows point in the only permitted direction; every vendor library is
confined to exactly one file, verified by grep.

```mermaid
flowchart TB
    subgraph tests["tests/ — 207 tests"]
        TT["unit · contract · integration<br/>inject a mock LLMClient<br/>autouse fixture blanks both API keys"]
    end

    subgraph ev["evals/ — pure observer"]
        EV["runner · metrics · judge · report<br/>owns its own ScriptedLLM"]
    end

    subgraph nodes["graph/nodes/ — 12 pure handlers"]
        ND["node state, deps -> state<br/>imports NO framework and NO SDK"]
    end

    subgraph seams["Typed seams — Protocols"]
        P1["LLMClient"]
        P2["Retriever"]
        P3["Embedder"]
        P4["SessionStore"]
        P5["LanguageDetector"]
        P6["Tool + ToolRegistry"]
        P7["Guardrail + SemanticClassifier"]
        P8["Judge — eval-side"]
    end

    subgraph impls["Implementations — each vendor in exactly ONE file"]
        I1["llm/anthropic_adapter.py<br/>the only 'import anthropic'"]
        I2["llm/openai_adapter.py<br/>the only chat 'import openai'"]
        I3["rag/embedder.py<br/>the only embeddings 'import openai'"]
        I4["graph/build.py<br/>the only 'from langgraph'"]
        I5["lang/detector.py<br/>the only 'from lingua'"]
        I6["rag/store.py<br/>the only 'from rank_bm25'"]
        I7["tools/normalize.py<br/>the only 'import phonenumbers'"]
        I8["rag/vector_store.py<br/>the only 'import numpy' + 'qdrant_client'"]
    end

    TT --> EV
    TT --> ND
    EV --> ND
    EV -.->|"deepeval lives here only"| I2
    ND --> P1
    ND --> P2
    ND --> P4
    ND --> P5
    ND --> P6
    ND --> P7
    P1 --> I1
    P1 --> I2
    P2 --> I6
    P2 --> I8
    P3 --> I3
    P2 --> P3
    P5 --> I5
    P6 --> I7
    P8 --> P1
    I4 -->|"wraps the nodes, is not imported BY them"| ND

    NEV["src/ never imports evals/ or tests/<br/>the dependency is strictly one-way"]
    NEV -.-> ND

    classDef det fill:#dcfce7,stroke:#16a34a,color:#052e16;
    classDef llm fill:#dbeafe,stroke:#2563eb,color:#0c1d51;
    class TT,EV,ND,P1,P2,P3,P4,P5,P6,P7,P8,I4,I5,I6,I7,I8,NEV det;
    class I1,I2,I3 llm;
```

This map is the reason the project survived a mid-build provider change. When the Anthropic account
ran out of credits, `config.yaml` flipped `provider: anthropic` to `openai` and one adapter file was
added — no node, no test, and no graph edge changed. A seam is only worth its cost if it is ever
actually used; this one was.

**Verified, not asserted:**

```bash
grep -rn "^\s*import anthropic\|^\s*from anthropic" src/   # → 1 file
grep -rn "^\s*from langgraph" src/                          # → 1 file
grep -rn "^\s*from lingua" src/                             # → 1 file
grep -rn "^\s*from rank_bm25" src/                          # → 1 file
grep -rn "import evals\|from evals" src/                    # → nothing
```

These belong in CI next to the tests — a seam decays the moment something reaches through it, and
nothing currently stops that.

---

## Where to go next

- **[architecture.md](architecture.md)** — the same system layer by layer, with the decisions, the
  rejected alternatives, the costs accepted, and the [ranked list of known gaps](architecture.md#known-gaps-ranked).
- **[docs/README.md](README.md)** — the six-layer summary table and the keyless verification commands.
- **[specs/](../specs/)** — the spec → plan → tasks → research artifacts each feature was built from.
