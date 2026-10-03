<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **auto_redbook** (7410 symbols, 18213 relationships, 554 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/auto_redbook/context` | Codebase overview, check index freshness |
| `gitnexus://repo/auto_redbook/clusters` | All functional areas |
| `gitnexus://repo/auto_redbook/processes` | All execution flows |
| `gitnexus://repo/auto_redbook/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |
| Work in the Tests area (1054 symbols) | `.claude/skills/gitnexus-area-tests/SKILL.md` |
| Work in the Apps area (475 symbols) | `.claude/skills/gitnexus-area-apps/SKILL.md` |
| Work in the Publish area (331 symbols) | `.claude/skills/gitnexus-area-publish/SKILL.md` |
| Work in the Workflow area (305 symbols) | `.claude/skills/gitnexus-area-workflow/SKILL.md` |
| Work in the Ai_digest area (219 symbols) | `.claude/skills/gitnexus-area-ai-digest/SKILL.md` |
| Work in the News area (168 symbols) | `.claude/skills/gitnexus-area-news/SKILL.md` |
| Work in the Images area (112 symbols) | `.claude/skills/gitnexus-area-images/SKILL.md` |
| Work in the Volcengine area (63 symbols) | `.claude/skills/gitnexus-area-volcengine/SKILL.md` |
| Work in the Aliyun area (51 symbols) | `.claude/skills/gitnexus-area-aliyun/SKILL.md` |
| Work in the Sources area (44 symbols) | `.claude/skills/gitnexus-area-sources/SKILL.md` |
| Work in the Llm area (43 symbols) | `.claude/skills/gitnexus-area-llm/SKILL.md` |
| Work in the Global_map area (31 symbols) | `.claude/skills/gitnexus-area-global-map/SKILL.md` |
| Work in the Storage area (28 symbols) | `.claude/skills/gitnexus-area-storage/SKILL.md` |
| Work in the Analytics area (28 symbols) | `.claude/skills/gitnexus-area-analytics/SKILL.md` |
| Work in the Siliconflow area (24 symbols) | `.claude/skills/gitnexus-area-siliconflow/SKILL.md` |
| Work in the Wool area (23 symbols) | `.claude/skills/gitnexus-area-wool/SKILL.md` |
| Work in the Knowledge area (20 symbols) | `.claude/skills/gitnexus-area-knowledge/SKILL.md` |
| Work in the Cluster_75 area (19 symbols) | `.claude/skills/gitnexus-area-cluster-75/SKILL.md` |
| Work in the Agent area (19 symbols) | `.claude/skills/gitnexus-area-agent/SKILL.md` |
| Work in the Cluster_76 area (18 symbols) | `.claude/skills/gitnexus-area-cluster-76/SKILL.md` |

<!-- gitnexus:end -->
