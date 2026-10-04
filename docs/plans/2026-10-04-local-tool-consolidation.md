# 工作流与独立智能体工具归拢实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 两个程序各自使用本项目内的工具代码与依赖，保留原工具、历史数据和账号配置。

**Architecture:** 工作流保留自己的 apps/src；智能体使用自己的 tools/redbook_tools 可编辑安装。两个项目分别持有 tools/worldmonitor、tools/RSSHub、tools/AIHOT、tools/opencodex 和 tools/postgresql。数据库、profile、草稿、素材和密钥继续使用原数据目录，不迁移或复制活动数据库。

**Tech Stack:** Python、PowerShell、Node.js、React、PostgreSQL 18.6。

**Spec:** 本轮用户的目录归拢要求。

## 全局约束

- 不在 C 盘安装内容，不更新第三方工具版本。
- 原始目录不删除，复制不得使用 /MIR、/PURGE 或 /MOVE。
- 不修改生成规则，不发帖、不删草稿、不发起收费模型调用。
- 智能体数据继续在 E:/AI/codex/redbook_runtime；工作流数据继续在项目 data/assets。
- AIHOT 的 PostgreSQL 数据继续在 E:/AI/codex/AIHOT-data。
- OpenCodex 的账号配置和服务状态继续使用现有本地配置，不复制凭证到工具代码目录，不修改 Codex 插件代理。
- PostgreSQL 不降级、不初始化新库、不改端口；共享数据的服务不能同时启动两份。

## 审查重点

1. 可编辑安装是否仍导入项目外的 redbook_tools。
2. pnpm 的绝对路径 Junction 是否仍回指 RSSHub 原目录。
3. AIHOT 未提交的本地修复及配置是否丢失。
4. 原数据、登录 profile 和生图请求状态是否保持不变。
5. 复制的第三方工具、环境文件、二进制或密钥是否进入 Git 跟踪。

## 任务 1：工具部署

**Files:** scripts/provision_local_tools.ps1、tools/README.md、.gitignore（两个项目）。

- [x] 从已有 checkout 本地克隆三个 Git 工具，覆盖复制现有依赖与必要的本地修复，保留源目录。
- [x] 复制现有 OpenCodex 软件包和 PostgreSQL 二进制到 tools；不复制账号池配置。
- [x] 对 RSSHub 内部 Junction 映射到新副本；检测越界链接并失败，不静默依赖源目录。
- [x] 写入不含秘密的本地工具清单；忽略第三方部署内容。

## 任务 2：入口与配置

**Files:** backend/settings.py、Start-Agent.cmd、Start-RSSHub.cmd、scripts/manage_postgresql.ps1、src/ai_digest/rsshub_local.py 及智能体对应副本。

- [x] 智能体可编辑安装重绑至 tools/redbook_tools；保留该包已有的独立数据区适配。
- [x] 两份本地 .env.gui 只替换工具路径，密钥、profile、额度、共享生图锁与状态保持不变。
- [x] PostgreSQL 管理脚本支持显式 RuntimeRoot，二进制从项目 tools 使用。
- [x] RSSHub 缺省目录改为本项目 tools，并将日志写入数据目录。
- [x] AIHOT 本地控制脚本适配副本位置，数据库和配置仍保留原位置。

## 任务 3：验证与交付

**Files:** tests/test_local_tools_layout.py（两个项目）、tests/test_app.py、README.md。

- [x] 路径回归测试先失败再通过：项目内导入、工具路径、日志路径、数据库凭据检查。
- [x] 测试现有 RSSHub、World Monitor、地图、图库和 Web API；实机读取 PostgreSQL 和本地已有草稿。
- [x] 分别从本地副本启动 RSSHub、World Monitor、AIHOT，检查服务响应并关闭测试进程。
- [x] 检查两个 CLI、前端构建和 API；受控重启闲置智能体 API，恢复可用。
- [x] 核对 Git 状态和忽略规则、数据计数及配置；没有重新生图/上传测试。

## 2026-10-04 验证记录

- 工作流集中回归 146 项通过；RSSHub 最后一次端口参数调整后额外 5 项通过。
- 智能体 API、导入隔离、进度与断点合同回归 48 项通过；其工具包图片策略回归 28 项通过。
- 两个前端均完成 TypeScript 检查与 Vite 构建；两个 CLI --help 正常。
- 两份 RSSHub 副本均返回 HTTP 200；必须设置 NODE_ENV=production 使用已构建路由，不能按开发模式查找 dist/routes。依赖包内的 logs 是代码目录，复制时只排除工具根目录的日志。
- World Monitor 副本分别返回 205/192 个条目，coverage=stale。这是服务和协议连通性证明，不是今日新闻的真实性/时效性验收；原有时效门禁没有放宽。
- 两份 AIHOT 副本分别启动、读取 /api/v1/items 返回 HTTP 200 后关闭；没有启动消费模型额度的 Worker。
- PostgreSQL 实机 ready：工作流 3344 份知识文档、智能体 4064 份；独立向量索引模型和维度保持不变。工作流数据库已通过本地 tools 二进制启动；智能体原有数据库进程继续运行，后续由新管理入口使用 tools 二进制，不为归拢代码强制停库。
- 本地 post.json 数量：工作流 3350、智能体 4149；草稿目录总数分别仍为 3890/4693，与调整前相同。
- 两份 OpenCodex 软件包版本 2.73.0、代码哈希校验通过，实时只读 preflight 确认为 chatgpt_subscription；没有生图或付费路由切换。
- 两份密钥配置逐行比对未变化；专用浏览器 profile 路径不变；原始工具和数据目录均保留。
- 没有公开发布、删除草稿或调用生成模型。原始 API Key、工具部署和数据均被 Git 忽略。
- 为避免不必要的大文件写入，取消了非必需的全库备份检查并清除了本次不完整产物；数据库没有迁移，配置备份仍保留。

## 回退

原目录一直保留。路径配置备份放在各数据目录的 backups/local-tools 下；如需回退，恢复这些配置并将智能体可编辑安装重绑至原 redbook_tools。数据库数据不搬动，因此无数据库回迁步骤。新工具副本仅由新的入口使用。
