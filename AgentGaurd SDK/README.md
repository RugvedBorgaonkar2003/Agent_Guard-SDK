# AgentGuard

**Stops your AI agents from colliding, looping forever, or blowing your budget.**

Open-source governance layer for multi-agent systems built with [CrewAI](https://github.com/crewAIInc/crewAI) and [LangGraph](https://github.com/langchain-ai/langgraph).

---

## The problem

A team once ran a multi-agent research system that cost $127/week. Two agents got stuck in a clarification loop — Agent A asked Agent B a question, B's answer prompted another question back to A — and it ran, undetected, for 11 days. By the time anyone noticed, the bill had climbed to **$47,000**.

This isn't a one-off. It's the predictable result of a gap that every multi-agent framework currently has: **agents can act, but nothing makes sure they don't collide with each other, and nothing stops a runaway pattern before it gets expensive.**

Specifically, frameworks like CrewAI and LangGraph give you:
- Step/recursion limits **per agent** — but no visibility into a repeating pattern *between* two or more agents talking to each other
- No concept of a shared lock — so two agents can read-modify-write the same resource at nearly the same moment, and one of their changes silently disappears
- No hard, real-time spending ceiling enforced *before* the next call — only a bill to review after the fact

AgentGuard sits in the execution path — not on the sidelines watching — and can say **no** before any of this happens.

## How this is different from LangSmith / tracing tools

LangSmith (and similar tools) are a security camera: they record everything and show you the footage afterward. AgentGuard is a security guard: it stands at the door in real time and can block an action *before* it happens.

They're complementary, not competing — use LangSmith to review and debug, use AgentGuard to prevent the expensive failures in the first place.

## What it does

- **Resource locking** — one agent holds a lock on a resource (a DB row, a file, an API), a second agent asking for the same one gets denied or queued, instead of silently overwriting the first.
- **Budget enforcement** — hard token/cost ceilings per agent and per workflow, checked *before* every call, not discovered after.
- **Loop detection** — watches the live event stream for repeating agent-to-agent message patterns and cuts them off automatically.
- **Live observability** — a terminal dashboard (built with [Textual](https://github.com/Textualize/textual)) showing active agents, spend, and locks in real time. No separate app, no browser — it lives in your terminal.
- **Audit trail** — every claim, release, budget check, and event is logged, so "why did my agent get blocked?" always has an answer.

### Deep Dive: The Loop Detection Engine

Solving infinite loops in multi-agent systems is incredibly difficult without destroying performance or memory. Here is how AgentGuard evolved to handle it:

1. **The Hash Problem:** We can't compare 10,000-word text strings efficiently, so we generate a 32-character MD5 hash of each prompt. It is blazing fast, but it fails on *Semantic Loops* (when agents repeat the exact same meaning using slightly different words).
2. **The Semantic Problem:** To catch Semantic Loops, we introduced Python's `SequenceMatcher` to mathematically score text similarity (e.g. `similarity > 0.85`). However, if we run this on *every* message, we burn CPU. If we store *every* raw text message forever to do this, our memory footprint blows up.
3. **The Final Architecture (Sliding Window & Suspicion Triggers):**
   - **Sliding Window:** We strictly cap the memory to the last 10 events. When event 11 comes in, event 1 is deleted. Memory stays perfectly flat forever.
   - **Suspicion Trigger:** We *only* run the heavy Semantic Check if the graph routing looks suspicious. If we see agents ping-ponging (e.g., `Agent_A` -> `Agent_B` -> `Agent_A` -> `Agent_B` repeating across the sliding window), the Semantic Check wakes up. Otherwise, it stays asleep.
   
This guarantees zero API costs, zero external dependencies, and near-zero latency.

### Deep Dive: LangGraph Auto-Instrumentation (Zero-Configuration)

To ensure the developer doesn't have to write custom guardrail code, AgentGuard hooks into LangChain's native `BaseCallbackHandler`. We intercept 4 specific lifecycle events under the hood:

1. **`on_chain_start` (Who is acting?)**
   We extract the `langgraph_node` from the metadata. This allows AgentGuard to know exactly which agent (e.g., "Agent_A") is currently running.
2. **`on_llm_start` (Loop & Budget Check)**
   Fires before an API call is made. We check the `LocalMemory` budget ceiling to prevent overspending. We also hash the prompt, save it to the Sliding Window, and check for Suspicious Ping-Pong patterns to trigger the Semantic SequenceMatcher. If any rule is broken, we raise an `AgentGuardException` which instantly aborts the agent.
3. **`on_llm_end` (The Cash Register)**
   Fires after a successful LLM response. We extract the exact `token_usage` from the provider's metadata, calculate the cost, and update the AgentGuard budget tracker.
4. **`on_tool_start` & `on_tool_end` (Database Locks)**
   Fires when an agent uses a tool. We map the `run_id` to a Resource Lock. If another agent holds the lock for that tool/database row, we block the action. When `on_tool_end` fires, we release the lock for the next agent.

### The AgentGuard Client (Configuration)

The developer interacts entirely with the `AgentGuard` class. It acts as a facade, hiding the complexity of `LocalMemory` and the Callbacks. It is designed with robust default values (like PyTorch) so it works out-of-the-box, but remains fully customizable:

```python
from agentguard import AgentGuard

guard = AgentGuard(
    budget_ceiling=10.0,            # Default: $10.00. Stops execution if exceeded.
    loop_threshold=15,              # Default: 15. The size of the Sliding Window to check for loops.
    semantic_sensitivity=0.90,      # Default: 0.90. The SequenceMatcher ratio required to trigger a Semantic Loop alarm.
    engine_url=None                 # Default: None (Uses fast Local Dictionary). Pass a Redis URL to switch to Production mode.
)

# Inject into LangGraph
graph.invoke(input, config={"callbacks": [guard.langgraph_callback()]})
```

### Deep Dive: Automatic Workflow Isolation (The "Wristband")

A major problem with zero-configuration SDKs is **Data Bleed**. If a developer runs three different LangGraph workflows simultaneously, how does the SDK prevent their sliding windows and budgets from mixing together into one chaotic pool?

1. **The Problem:** Forcing developers to manually generate and pass a unique `workflow_id` for every single execution is tedious and ruins the developer experience.
2. **The Solution:** We utilize LangChain's hidden execution tree. When a graph is invoked, it generates a root UUID. Every agent inside that graph is permanently stamped with a `parent_run_id` pointing back to that root (like a digital wristband). 
3. **The Result:** AgentGuard secretly reads this `parent_run_id` and uses it to automatically create perfectly isolated memory folders for every concurrent execution in real-time. No manual IDs required.

*(Note: If the developer *wants* to track an overarching budget across multiple executions, they can still explicitly pass `guard.langgraph_callback(workflow_id="sales_team")`, which elegantly overrides the automatic isolation).*

### The Lazy Code Vulnerability & The Node-Level Pivot

During testing, we discovered a fatal flaw in relying on LangChain's internal LLM callbacks.

1. **The Problem:** If a developer writes "lazy" code and forgets to explicitly pass `config=config` into their LLM invocation (e.g., `llm.invoke(state)` instead of `llm.invoke(state, config=config)`), LangChain drops the callback. AgentGuard goes completely blind and the agent can loop infinitely without triggering the safety nets.
2. **The Solution:** We executed a major architectural pivot. We ripped the entire Loop Detection algorithm out of the LLM boundary (`on_llm_start`) and moved it directly into the Graph Node boundary (`on_chain_start`). 
3. **The Result:** LangGraph guarantees that `on_chain_start` fires for every single Node automatically, carrying the exact state of the graph with it. AgentGuard now intercepts the state, extracts the last message, and runs the Sliding Window (Deque) and SequenceMatcher checks *before the node even executes*. The SDK is now 100% Zero-Configuration and completely immune to lazy developer code.

### The "Swallowed Exception" Problem (The Emergency Brake)

During final verification, we encountered a hidden LangChain behavior. 

1. **The Problem:** LangChain callbacks are designed to be non-obtrusive loggers. By default, if a callback throws an exception, LangChain catches it, prints a warning to the console, and *swallows* the error, allowing the main graph to continue executing infinitely. This completely neutralizes AgentGuard's ability to act as an emergency brake.
2. **The Solution:** We explicitly configured our `AgentGuardCallback` with the hidden `self.raise_error = True` parameter. 
3. **The Result:** LangChain is now forced to respect our `AgentGuardException`. The exact millisecond a loop is detected, AgentGuard pulls the emergency brake and physically crashes the graph execution, preventing run-away API costs.

## Status

🚧 Actively being built in public. This is an early MVP focused on CrewAI + LangGraph support. Contributions, issues, and "this blocked something it shouldn't have" reports are especially welcome — false positives are the failure mode we most want to catch early.

## Quickstart

```bash
# clone and bring up the engine (FastAPI + Postgres + Redis)
git clone https://github.com/<your-username>/agentguard.git
cd agentguard
docker compose up

# in your agent project
pip install agentguard-sdk
```

Protect an existing CrewAI crew in three lines:

```python
from agentguard import AgentGuard

guard = AgentGuard(api_key="your-key", engine_url="http://localhost:8000")
crew = Crew(agents=[...], tasks=[...], callbacks=guard.crewai_hooks())
```

Or a LangGraph graph:

```python
from agentguard import AgentGuard

guard = AgentGuard(api_key="your-key", engine_url="http://localhost:8000")
graph = builder.compile(middleware=[guard.langgraph_middleware()])
```

Watch it live:

```bash
agentguard dashboard
```

## Architecture

```
CrewAI / LangGraph agent
        │
        ▼
  AgentGuard SDK (hooks/middleware)
        │
        ▼
  AgentGuard engine (FastAPI)
    ├── Redis   → live locks, budget counters, heartbeats
    └── Postgres → durable registry, audit log, history
        │
        ▼
  Terminal dashboard (Textual)
```

## Tech stack

Python end to end: FastAPI, SQLModel, PostgreSQL, Redis, Textual. See [`agentguard-planning.md`](./agentguard-planning.md) for the full schema and API design.

## Contributing

Issues and PRs welcome. If AgentGuard blocks something it shouldn't have, that's the most valuable bug report you can file — please include your framework, version, and what you expected to happen.

## License

Apache 2.0