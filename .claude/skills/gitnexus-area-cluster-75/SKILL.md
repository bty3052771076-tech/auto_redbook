---
name: gitnexus-area-cluster-75
description: "Skill for the Cluster_75 area of auto_redbook. 19 symbols across 3 files."
---

# Cluster_75

19 symbols | 3 files | Cohesion: 64%

## When to Use

- Working with code in `frontend/`
- Understanding how DeleteDrafts, change, connect work
- Modifying cluster_75-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `frontend/src/main.tsx` | App, submit, Creation, loadFile, run (+10) |
| `frontend/src/WorkbenchTools.tsx` | DeleteDrafts, change |
| `frontend/src/api.ts` | connect, imageURL |

## Entry Points

Start here when exploring this area:

- **`DeleteDrafts`** (Function) — `frontend/src/WorkbenchTools.tsx:8`
- **`change`** (Function) — `frontend/src/WorkbenchTools.tsx:25`
- **`connect`** (Function) — `frontend/src/api.ts:139`
- **`imageURL`** (Function) — `frontend/src/api.ts:167`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `DeleteDrafts` | Function | `frontend/src/WorkbenchTools.tsx` | 8 |
| `change` | Function | `frontend/src/WorkbenchTools.tsx` | 25 |
| `connect` | Function | `frontend/src/api.ts` | 139 |
| `imageURL` | Function | `frontend/src/api.ts` | 167 |
| `App` | Function | `frontend/src/main.tsx` | 2241 |
| `submit` | Function | `frontend/src/main.tsx` | 2315 |
| `Creation` | Function | `frontend/src/main.tsx` | 792 |
| `loadFile` | Function | `frontend/src/main.tsx` | 862 |
| `run` | Function | `frontend/src/main.tsx` | 832 |
| `DraftDrawer` | Function | `frontend/src/main.tsx` | 1635 |
| `Field` | Function | `frontend/src/main.tsx` | 391 |
| `GlobalMapPage` | Function | `frontend/src/main.tsx` | 1134 |
| `createMap` | Function | `frontend/src/main.tsx` | 1175 |
| `ImagePreview` | Function | `frontend/src/main.tsx` | 1608 |
| `PostProgress` | Function | `frontend/src/main.tsx` | 1570 |
| `ProviderManagement` | Function | `frontend/src/main.tsx` | 698 |
| `selectable` | Function | `frontend/src/main.tsx` | 751 |
| `SettingsPage` | Function | `frontend/src/main.tsx` | 2154 |
| `Status` | Function | `frontend/src/main.tsx` | 82 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `App → Api` | cross_community | 4 |
| `Drafts → Api` | cross_community | 4 |
| `SettingsPage → Api` | cross_community | 4 |
| `Creation → Empty` | cross_community | 3 |
| `Creation → Field` | intra_community | 3 |
| `Creation → CreateMap` | intra_community | 3 |
| `Creation → Status` | intra_community | 3 |

## How to Explore

1. `context({name: "DeleteDrafts"})` — see callers and callees
2. `query({search_query: "cluster_75"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
