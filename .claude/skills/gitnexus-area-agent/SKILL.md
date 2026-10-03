---
name: gitnexus-area-agent
description: "Skill for the Agent area of auto_redbook. 19 symbols across 1 files."
---

# Agent

19 symbols | 1 files | Cohesion: 97%

## When to Use

- Working with code in `src/`
- Understanding how finish, generate, next_job work
- Modifying agent-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/agent/editorial_agent.py` | finish, generate, next_job, persist, plan (+14) |

## Entry Points

Start here when exploring this area:

- **`finish`** (Function) — `src/agent/editorial_agent.py:608`
- **`generate`** (Function) — `src/agent/editorial_agent.py:372`
- **`next_job`** (Function) — `src/agent/editorial_agent.py:593`
- **`persist`** (Function) — `src/agent/editorial_agent.py:304`
- **`plan`** (Function) — `src/agent/editorial_agent.py:328`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `finish` | Function | `src/agent/editorial_agent.py` | 608 |
| `generate` | Function | `src/agent/editorial_agent.py` | 372 |
| `next_job` | Function | `src/agent/editorial_agent.py` | 593 |
| `persist` | Function | `src/agent/editorial_agent.py` | 304 |
| `plan` | Function | `src/agent/editorial_agent.py` | 328 |
| `recover` | Function | `src/agent/editorial_agent.py` | 570 |
| `review` | Function | `src/agent/editorial_agent.py` | 407 |
| `stop_if_budget_exceeded` | Function | `src/agent/editorial_agent.py` | 310 |
| `sync_context` | Function | `src/agent/editorial_agent.py` | 361 |
| `upload` | Function | `src/agent/editorial_agent.py` | 451 |
| `_checkpoint_payload` | Function | `src/agent/editorial_agent.py` | 219 |
| `_content_version` | Function | `src/agent/editorial_agent.py` | 186 |
| `_emit` | Function | `src/agent/editorial_agent.py` | 275 |
| `_job_from_dict` | Function | `src/agent/editorial_agent.py` | 174 |
| `_post_id` | Function | `src/agent/editorial_agent.py` | 178 |
| `_post_ids` | Function | `src/agent/editorial_agent.py` | 182 |
| `_redact_text` | Function | `src/agent/editorial_agent.py` | 25 |
| `_safe_value` | Function | `src/agent/editorial_agent.py` | 199 |
| `_save_checkpoint` | Function | `src/agent/editorial_agent.py` | 252 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Finish → _post_id` | intra_community | 6 |
| `Finish → _redact_text` | intra_community | 6 |
| `Generate → _post_id` | intra_community | 6 |
| `Generate → _redact_text` | intra_community | 6 |
| `Next_job → _post_id` | intra_community | 6 |
| `Next_job → _redact_text` | intra_community | 6 |
| `Recover → _post_id` | intra_community | 6 |
| `Recover → _redact_text` | intra_community | 6 |
| `Review → _post_id` | intra_community | 6 |
| `Review → _redact_text` | intra_community | 6 |

## How to Explore

1. `context({name: "finish"})` — see callers and callees
2. `query({search_query: "agent"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
