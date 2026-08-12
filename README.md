# AgentGuard SDK 🛡️

> **Runtime guardrails for multi-agent AI systems.**
>
> Detect runaway agent loops, enforce workflow budgets, and prevent conflicting resource access before your agents turn a small execution problem into an expensive one.

[![PyPI](https://img.shields.io/pypi/v/agentguard-sdk)](https://pypi.org/project/agentguard-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/agentguard-sdk)](https://pypi.org/project/agentguard-sdk/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> ⚠️ **V1 / Experimental**
>
> AgentGuard is currently in its first public build. It is intended for **testing, experimentation, and developer feedback**, not production-critical workloads.

---

## What problem does AgentGuard solve?

Multi-agent AI systems introduce a failure mode that is easy to miss:

**an agent can continue acting even when the overall workflow has gone wrong.**

Consider a simple multi-agent workflow:

```text
Agent A
   ↓
Agent B
   ↓
Agent A
   ↓
Agent B
   ↓
Agent A
   ↓
   ...
```

Each individual agent may be behaving correctly.

The problem appears at the **workflow level**.

Two agents can repeatedly communicate with each other, consume model calls, accumulate tokens, modify shared resources, and continue running without an obvious failure at the individual-agent level.

Traditional application safeguards such as per-agent recursion limits don't necessarily understand this **agent-to-agent interaction**.

This creates three important risks:

* 🔁 **Runaway loops** — agents repeatedly trigger one another.
* 💸 **Uncontrolled spending** — a workflow continues making LLM calls beyond its intended budget.
* 🔒 **Resource conflicts** — multiple agents attempt to modify the same resource concurrently.

AgentGuard was built to provide a runtime safety layer for these situations.

---

# What is AgentGuard?

**AgentGuard is a lightweight governance SDK that sits inside your agent workflow and monitors execution as it happens.**

Instead of being primarily an observability system that tells you what happened after an execution, AgentGuard is designed to act as an **execution-time guardrail**.

```text
                    Your AI Application
                           │
                           ▼
                  ┌─────────────────┐
                  │   AgentGuard    │
                  │                 │
                  │  Loop Detection │
                  │  Budget Guard   │
                  │  Resource Lock  │
                  └────────┬────────┘
                           │
                           ▼
                    Agent Workflow
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           Agent A      Agent B      Agent C
```

The goal is simple:

> **Let your agents act freely — but give the workflow an emergency brake.**

---

# AgentGuard vs. Observability Platforms

Tools such as LangSmith are extremely useful for **observability, tracing, debugging, evaluation, and understanding what happened inside an LLM application**.

AgentGuard addresses a different layer.

|                        | Observability           | AgentGuard                     |
| ---------------------- | ----------------------- | ------------------------------ |
| Primary goal           | Understand executions   | Guard executions               |
| Main focus             | Traces, logs, debugging | Runtime safety                 |
| Detects loops          | Can help identify them  | Designed to stop them          |
| Budget visibility      | Monitoring / analysis   | Runtime budget enforcement     |
| Resource locking       | ❌                       | ✅                              |
| Execution intervention | Primarily observability | Designed as an execution guard |
| Position               | Around the application  | Inside the execution path      |

**AgentGuard is not intended to replace LangSmith.**

They can be complementary:

```text
              AI Application
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
     AgentGuard          LangSmith
     "Stop it"           "Understand it"
          │                 │
          └────────┬────────┘
                   ▼
              Agent Workflow
```

Use observability tooling when you want to understand and analyze your system.

Use AgentGuard when you want **runtime guardrails around the system itself**.

---

# What AgentGuard currently provides

## 🔁 1. Agent Loop Detection

AgentGuard monitors the execution stream for suspicious agent-to-agent repetition.

It doesn't rely exclusively on exact string matching.

The V1 implementation combines:

* A bounded sliding window
* Agent-to-agent routing patterns
* Fast message hashing
* Semantic similarity checks using `SequenceMatcher`
* Suspicion-triggered semantic analysis

This allows AgentGuard to detect situations where agents are effectively repeating the same interaction even when the exact wording changes.

### Why a sliding window?

Keeping the entire execution history in memory would continuously increase memory usage.

AgentGuard instead maintains a bounded window:

```text
Event 1
Event 2
Event 3
...
Event 15
```

When a new event arrives:

```text
Event 16
```

the oldest event leaves the window:

```text
Event 2
Event 3
...
Event 16
```

This keeps the memory footprint bounded.

### Why not run semantic similarity on every event?

Semantic comparison is more expensive than simple structural checks.

AgentGuard therefore uses a **suspicion trigger**.

```text
New event
   │
   ▼
Is the routing pattern suspicious?
   │
   ├── No ──► Continue
   │
   └── Yes
          │
          ▼
   Semantic similarity check
          │
          ├── Normal ──► Continue
          │
          └── Loop ──► Stop execution
```

The intention is to keep the expensive check away from normal execution paths.

---

# 💰 2. Budget Enforcement

AgentGuard allows you to define a spending ceiling for a workflow.

For example:

```python
guard = AgentGuard(
    budget_ceiling=10.0
)
```

The workflow can then be guarded against exceeding the configured budget.

The important design principle is:

> **A budget should be enforced during execution, not discovered only after the bill arrives.**

AgentGuard is intended to provide a runtime boundary around the workflow's allowed spend.

---

# 🔒 3. Resource Locking

Multi-agent systems can have multiple agents interacting with shared resources.

For example:

```text
Agent A ─────┐
             ├──► Database Row
Agent B ─────┘
```

Without coordination, both agents may attempt to modify the same resource concurrently.

AgentGuard's resource-locking layer is intended to prevent these conflicting operations.

This capability is part of the project's broader goal:

> **Govern what agents are allowed to do while they are executing.**

---

# How AgentGuard works

AgentGuard was designed around a few problems discovered while building V1.

## 1. Exact matching wasn't enough

A simple hash can quickly identify identical messages:

```text
"Ask the database for customer 123"
        ↓
       hash
```

But semantic loops don't always repeat the exact same text:

```text
"Find information about customer 123"

"Retrieve the customer 123 details"

"Can you look up data for customer 123?"
```

These messages can represent essentially the same interaction.

AgentGuard therefore introduced semantic similarity analysis on suspicious execution patterns.

---

## 2. Unlimited history creates a memory problem

Keeping every event indefinitely would make the guard's memory usage grow with execution length.

V1 solves this with a bounded `deque`-based sliding window.

```text
Bounded memory
      ↓
Recent execution context
      ↓
Suspicion detection
      ↓
Semantic verification
```

---

## 3. Multiple workflows must not share state

A zero-configuration SDK cannot ask developers to manually create a unique workflow ID every time they execute a graph.

LangGraph already provides execution metadata that can be used to associate child executions with their parent workflow.

AgentGuard uses this execution context to isolate workflow state.

Conceptually:

```text
Workflow A
   ├── Agent 1
   ├── Agent 2
   └── Agent 3

Workflow B
   ├── Agent 1
   └── Agent 2
```

The state associated with Workflow A should not accidentally become part of Workflow B.

AgentGuard therefore creates execution-level isolation automatically.

Developers can also explicitly provide a workflow identifier when they want multiple executions to share a broader budget or tracking boundary.

---

## 4. LLM-level callbacks were not reliable enough

During development, a major problem appeared:

A developer could invoke an LLM without correctly propagating the callback configuration.

That meant the guard could lose visibility into the execution.

The architecture therefore moved the core loop-detection logic away from relying solely on the LLM boundary and toward the **graph/node execution boundary**.

Conceptually:

```text
Before:

Graph
  ↓
Node
  ↓
LLM
  ↓
Callback
  ↓
Guard


V1 approach:

Graph
  ↓
Node boundary
  ↓
AgentGuard
  ↓
Loop / budget checks
  ↓
Node execution
```

This makes the guard less dependent on developers manually passing callback configuration through every individual model invocation.

---

# 5. The "swallowed exception" problem

Another important discovery during development was that callback exceptions can be handled differently from normal application exceptions.

If a guard raises an exception but the framework treats callback failures as non-critical, the workflow may continue.

That defeats the purpose of an emergency brake.

AgentGuard therefore configures its callback behavior so that the guard's exception can propagate and stop the execution when a configured safety condition is triggered.

Conceptually:

```text
Loop detected
     │
     ▼
AgentGuardException
     │
     ▼
Execution interrupted
```

The goal is not simply to **report** that a loop happened.

The goal is to prevent the runaway execution from continuing.

---

# Installation

AgentGuard is currently distributed through PyPI.

```bash
pip install agentguard-sdk
```

Then install the framework integration you intend to use.

For the current LangGraph integration:

```bash
pip install langgraph
```

If your application already uses LangChain/LangGraph, install the versions required by your application as usual.

---

# Quick Start — LangGraph

A minimal integration looks like this:

```python
from AgentGaurd_SDK.client import AgentGuard
from langgraph.graph import StateGraph

# 1. Create the guard
guard = AgentGuard(
    budget_ceiling=10.0,
    loop_threshold=15,
    semantic_sensitivity=0.90,
)

# 2. Build your LangGraph normally
builder = StateGraph(AgentState)

# Add your nodes and edges...
# builder.add_node(...)
# builder.add_edge(...)

graph = builder.compile()

# 3. Attach AgentGuard to the graph execution
result = graph.invoke(
    {"messages": [HumanMessage(content="Hello!")]},
    config={
        "callbacks": [
            guard.langgraph_callback()
        ]
    },
)
```

That's the basic integration model:

```text
Create Guard
     ↓
Build Graph
     ↓
Compile Graph
     ↓
Attach Guard callback
     ↓
Invoke Graph
```

---

# Configuration

The V1 guard can be configured with parameters such as:

```python
guard = AgentGuard(
    budget_ceiling=10.0,
    loop_threshold=15,
    semantic_sensitivity=0.90,
)
```

### `budget_ceiling`

Maximum configured spending boundary for the guarded workflow.

```python
budget_ceiling=10.0
```

### `loop_threshold`

Controls the number of events considered within the loop-detection window.

```python
loop_threshold=15
```

### `semantic_sensitivity`

Controls how similar messages must be before they are treated as a potential semantic repetition.

```python
semantic_sensitivity=0.90
```

Higher values generally require closer similarity.

---

# Explicit Workflow IDs

AgentGuard can automatically isolate executions based on the workflow execution context.

If you want to explicitly group executions under a common workflow identifier, you can provide one:

```python
guard.langgraph_callback(
    workflow_id="sales_team"
)
```

This can be useful when you want a broader budget or tracking boundary across multiple executions.

---

# Current Framework Support

### V1

| Framework | Status                                |
| --------- | ------------------------------------- |
| LangGraph | ✅ Available                           |
| LangChain | 🟡 Used through LangGraph integration |
| CrewAI    | 🚧 Planned                            |

AgentGuard is currently being developed toward a framework-agnostic architecture, but **V1 should be considered primarily a LangGraph-focused implementation**.

---

# Current Architecture

At a high level:

```text
                   LangGraph
                       │
                       ▼
              ┌─────────────────┐
              │   AgentGuard    │
              ├─────────────────┤
              │                 │
              │ Workflow        │
              │ Isolation       │
              │                 │
              │ Loop Detection  │
              │                 │
              │ Budget Guard    │
              │                 │
              │ Resource Locks  │
              │                 │
              └────────┬────────┘
                       │
                       ▼
                Graph Execution
```

The V1 implementation primarily uses local in-process state.

This is intentional for the current development stage.

---

# V1 Status & Limitations

AgentGuard is **not production-ready yet**.

This release is a public V1 intended to answer questions such as:

* Does the guard detect real-world multi-agent loops reliably?
* Are the detection thresholds useful?
* How much overhead does the guard introduce?
* Are the budget boundaries accurate enough?
* Does the resource-locking model work for practical workflows?
* What failure modes have not yet been covered?
* What framework abstractions are needed for broader support?

The project is being developed publicly so developers can test it, break it, report edge cases, and help shape future versions.

### Known V1 direction

The current implementation is:

* Local / in-process
* LangGraph-focused
* Experimental
* Not yet designed for distributed production workloads
* Subject to API and architecture changes

**If you test AgentGuard, feedback is highly valuable.**

Open an issue with:

1. Your framework/version
2. Agent topology
3. Expected behavior
4. Actual behavior
5. Relevant logs or minimal reproduction

---

# Roadmap

AgentGuard is being developed in four planned phases.

### Phase 1 — Foundation

* [x] Local execution memory
* [x] Sliding-window loop detection
* [x] Semantic similarity checks
* [x] LangGraph integration
* [x] Node-level execution guardrails
* [x] Workflow isolation

**Current phase**

### Phase 2 — Framework Expansion

* [ ] Native CrewAI integration
* [ ] Additional agent framework integrations
* [ ] Common framework abstraction layer

### Phase 3 — Developer Dashboard

* [ ] Terminal/TUI monitoring
* [ ] Real-time execution windows
* [ ] Budget visualization
* [ ] Loop visualization
* [ ] Guard events and diagnostics

### Phase 4 — Distributed Runtime

* [ ] Redis-backed state
* [ ] PostgreSQL-backed state
* [ ] Distributed resource locks
* [ ] Production-scale workflow coordination

---

# Why build this?

Agentic systems are moving from single model calls toward workflows where multiple autonomous components can reason, call tools, communicate, and modify shared state.

That creates a different class of engineering problems.

The question is no longer only:

> **"Did my model give a good answer?"**

It also becomes:

> **"What happens when my agents behave incorrectly together?"**

AgentGuard is an attempt to build the missing runtime safety layer around that problem.

---

# Contributing

AgentGuard is open source and currently maintained by:

**Rugved Milind Borgaonkar**

The project is intentionally being developed in public.

If you find a bug, discover an edge case, have an idea for a guardrail, or want to experiment with the architecture:

1. Open an issue.
2. Describe the problem clearly.
3. Include a minimal reproduction where possible.
4. Explain what behavior you expected.
5. For larger changes, open a pull request with context.

As the project grows, formal contribution guidelines will be added separately.

---

# License

AgentGuard SDK is released under the **MIT License**.

Copyright © 2026 **Rugved Milind Borgaonkar**

See [`LICENSE`](LICENSE) for the complete license text.

---

# Author

**Rugved Milind Borgaonkar**

Built as an open-source experiment into runtime governance and safety for multi-agent AI systems.

If you are building multi-agent systems with LangGraph and test AgentGuard, feedback on what breaks, what is missing, and what should be redesigned is especially welcome.

---

## Project Status

```text
AgentGuard SDK
Version: 0.1.0
Status: Experimental / V1
Primary integration: LangGraph
License: MIT
Maintainer: Rugved Milind Borgaonkar
```
