---
name: gitnexus-area-cluster-76
description: "Skill for the Cluster_76 area of auto_redbook. 18 symbols across 3 files."
---

# Cluster_76

18 symbols | 3 files | Cohesion: 68%

## When to Use

- Working with code in `frontend/`
- Understanding how LocalConfiguration, refresh, save work
- Modifying cluster_76-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `frontend/src/main.tsx` | executePlan, newConversation, sendMessage, id, reload (+7) |
| `frontend/src/WorkbenchTools.tsx` | LocalConfiguration, refresh, save, SourceHealth, refresh |
| `frontend/src/api.ts` | api |

## Entry Points

Start here when exploring this area:

- **`LocalConfiguration`** (Function) — `frontend/src/WorkbenchTools.tsx:88`
- **`refresh`** (Function) — `frontend/src/WorkbenchTools.tsx:90`
- **`save`** (Function) — `frontend/src/WorkbenchTools.tsx:92`
- **`SourceHealth`** (Function) — `frontend/src/WorkbenchTools.tsx:51`
- **`refresh`** (Function) — `frontend/src/WorkbenchTools.tsx:54`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `LocalConfiguration` | Function | `frontend/src/WorkbenchTools.tsx` | 88 |
| `refresh` | Function | `frontend/src/WorkbenchTools.tsx` | 90 |
| `save` | Function | `frontend/src/WorkbenchTools.tsx` | 92 |
| `SourceHealth` | Function | `frontend/src/WorkbenchTools.tsx` | 51 |
| `refresh` | Function | `frontend/src/WorkbenchTools.tsx` | 54 |
| `api` | Function | `frontend/src/api.ts` | 147 |
| `executePlan` | Function | `frontend/src/main.tsx` | 1342 |
| `newConversation` | Function | `frontend/src/main.tsx` | 1305 |
| `sendMessage` | Function | `frontend/src/main.tsx` | 1318 |
| `id` | Function | `frontend/src/main.tsx` | 2273 |
| `reload` | Function | `frontend/src/main.tsx` | 2257 |
| `refresh` | Function | `frontend/src/main.tsx` | 1796 |
| `checkCoverage` | Function | `frontend/src/main.tsx` | 1156 |
| `refresh` | Function | `frontend/src/main.tsx` | 1460 |
| `refresh` | Function | `frontend/src/main.tsx` | 1983 |
| `resetForm` | Function | `frontend/src/main.tsx` | 728 |
| `saveBindings` | Function | `frontend/src/main.tsx` | 747 |
| `saveProvider` | Function | `frontend/src/main.tsx` | 732 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `AgentWorkspace → Api` | cross_community | 4 |
| `App → Api` | cross_community | 4 |
| `Drafts → Api` | cross_community | 4 |
| `SettingsPage → Api` | cross_community | 4 |
| `AnalysisReport → Api` | cross_community | 3 |
| `SourceHealth → Api` | intra_community | 3 |
| `Timer → Api` | cross_community | 3 |
| `Id → Api` | intra_community | 3 |
| `SaveBindings → Api` | intra_community | 3 |
| `SaveProvider → Api` | intra_community | 3 |

## How to Explore

1. `context({name: "LocalConfiguration"})` — see callers and callees
2. `query({search_query: "cluster_76"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
