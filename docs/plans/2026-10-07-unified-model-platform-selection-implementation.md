# 统一模型平台选择：实施与测试记录

日期：2026-10-07
设计依据：`2026-10-07-unified-model-platform-selection-design.md`
范围：工作流、独立智能体及其自带工具。未执行新闻生成、小红书上传/发布、额度同步或 GitHub 推送。

## 1. 已实现的第一阶段

- 新增共同版本的 `src/model_platforms/`，独立智能体使用自己的 `tools/redbook_tools/src/model_platforms/`，不依赖旧工作流目录。
- 支持自定义 OpenAI Chat Completions、OpenAI Responses、Claude Messages，以及 Gemini/Ollama 等兼容协议连接。原生模型 ID 保留斜杠、冒号，使用不透明 `model_ref` 进行本地选择。
- 供应商连接、模型目录、能力验证、费用授权、默认角色分别存储；同一厂商可以创建多个连接。手动模型无需枚举接口。
- 主控、写稿、生图独立选择。主控/校准/压缩共用主控解析；写稿走写稿配置。生图保留原有实现，不因换 LLM 改写图片链路。
- 两套 Web GUI 接通供应商管理、模型发现、手动添加、参数编辑、凭据替换、启停、能力测试和默认角色。独立智能体增加“本次模型”，只修改当前待确认计划。
- 主控和写稿实际调用对应协议；不再把原生 Messages/Responses 伪装成 Chat。只提取最终输出，截断、拒绝、无正文和非法工具参数报错。
- 自定义调用不进入旧生成器自动重放或其他供应商回退。401/429/超时等返回可操作原因，不自动同步额度或切换付费 PPInfra。
- 本次自定义模型快照写入 Web 运行和智能体检查点；续跑恢复原快照。原授权撤销、凭据轮换或显式覆盖冲突会停止相应调用，不静默改用新的默认模型。
- 自定义 LLM 费用授权不依赖传统免费 LLM 额度快照；图片仍遵守已有免费/订阅限制，正余额的按量图片模型不自动获准。

第二阶段未启用：原生 Gemini `generateContent`、新的自定义生图及自定义视觉审核。现有 MiniMax/opencodex 图片方式继续保留。其他厂商可通过自定义兼容连接配置，不宣称全部厂商均已实测。

## 2. GUI 快速使用

1. 重启所用程序的 Web 服务。工作流进入“模型与供应商”；独立智能体进入“连接与模型”。已有 MiniMax 配置继续可用，无需重新同步额度。
2. 点击“添加供应商”，选择模板或“自定义 API”，填写 API 基址、实际协议、认证方式和 Key。公网只能 HTTPS；本机服务需明确 loopback 及 1024 以上端口。保存连接本身不调用模型。
3. 使用“更新模型列表”或“添加模型”。新发现的模型默认不启用，手动输入原生模型 ID 后自行启用。目录失败/不完整保留原目录，不自动换默认模型。
4. 为该连接“授权此连接”：明确主控/写稿角色、有效期和本地请求次数，确认费用风险。这里不是充值，不证明厂商余额免费或无限，失败请求也可能计入请求次数。
5. 写稿至少“测试文本”；主控至少“测试结构化”；需要检查函数回环时用“测试工具回环”。验证有效期 24 小时，与额度同步不同。
6. 在“默认角色”分别选择主控、写稿和已有生图模型并保存。也可在智能体对话的“本次模型”中调整后点击“应用于本次计划”，不会更改默认配置。
7. 之后使用原有工作流或发送任务消息。大模型校准使用本次计划主控；对话压缩继承最新计划主控。确认后冻结模型，运行期间改变默认值不改正在执行的自定义角色。

编辑 token/temperature/top_p/推理参数会清除旧能力证据，需重新测试。基址或协议变更须新建连接并重新授权，避免把旧 Key 发到新认证目标。

## 3. CLI

在对应程序的工具工作目录中使用其原有 Python 环境：

```powershell
python -m apps.cli model-platforms --help
python -m apps.cli model-platforms list
python -m apps.cli model-platforms presets
python -m apps.cli model-platforms models
python -m apps.cli model-platforms roles
```

管理命令还包括 `add`、`authorize`、`discover`、`enable-model`、`check`、`resolve`。用各命令 `--help` 查看参数。CLI 不接收字面量 Key，使用 `--credential-env` 引用已有环境变量；Claude 默认使用 `x-api-key`。

角色覆盖放在子命令之前，例如：

```powershell
python -m apps.cli --writer-model-ref m_实际引用 auto --help
python -m apps.cli --controller-model-ref m_实际引用 agent --help
```

示例中的 `--help` 只显示帮助，不生成或上传。续跑使用原有 `--resume-from`。缺少自定义快照的旧检查点不会自动采用新默认；原有纯旧模型检查点保持兼容。

## 4. 存储与安全

| 程序 | 默认位置 |
| --- | --- |
| 工作流 | `E:/AI/codex/redbook_workflow/data/model_platforms/` |
| 独立智能体 | `E:/AI/codex/redbook_runtime/data/model_platforms/` |

可显式设置 `MODEL_PLATFORMS_DIR` 共用目录；`MODEL_PLATFORMS_NAMESPACE` 分别为 `workflow`、`agent`，默认角色互不覆盖。独立智能体 CLI 使用运行区目录和 agent namespace，与 GUI 一致。

- `registry.json` 是非秘密配置；Windows Key 用当前账户 DPAPI 加密存于 `secrets/`。服务器通过环境变量引用，不降级明文文件。
- 环境变量 Key 有本地 HMAC 指纹。值变化后旧能力、授权和快照不能直接转到新账户，需显式替换凭据、重新授权及测试。
- 默认角色在一个 registry CAS 事务中保存；旧 `providers.json` 只用于兼容读取，不再双文件镜像写角色。
- 本地 OS 文件锁协调配置修改、请求次数与同限流组并发；连接并发可设 1–5，实际按共享组的较小限制执行。图片队列及平台上传串行规则不变。不宣称本地锁能协调多主机。
- 公网 DNS 必须为全球可路由地址；直连和 HTTPS 代理均使用已校验 IP，TLS 校验/SNI/Host 保留原 API 域名。禁止跟随跨域重定向或关闭证书校验。
- 后台模型检查使用租约；进程中断后返回 `OPERATION_INTERRUPTED`，不永久显示 running，也不自动重新消耗请求。
- 两套程序的 `data/` 已被 Git 忽略。本次未安装任何 C 盘依赖，测试产物统一保留在 E 盘 `data/tmp/`。
- PostgreSQL 知识库、记忆与生产恢复方式未降级。测试中使用的内存存储是明确的隔离测试替身。

## 5. 验证证据

测试使用合成 Key、本地受控 HTTP/HTTPS 服务及 MockTransport，不接触真实厂商余额或小红书。

- 三协议编解码、实际生成入口、主控校准/压缩、费用/角色隔离、CAS、凭据轮换、目录新增/下架/partial、参数失效、输出截断和快照篡改均有自动化用例。
- 两套真实本地 API + Chromium GUI：添加连接、录入模型、授权、结构化验证、角色绑定、刷新保留、390px 不溢出；独立智能体另测本次计划模型保存。
- 实际本地 HTTPS 代理隧道：核对 CONNECT 固定 IP、原域名 SNI/Host、证书校验成功；没有关闭 TLS 校验。
- 实际 Windows 双进程：同版本争写只有一次成功；共享并发 1 的调用时间段不重叠；请求次数准确累加。
- Windows DPAPI：密文读回及公开配置/错误中合成 Key 不泄漏。
- 工作流完整回归：1483 passed、8 skipped，耗时 422.50 秒；日志在 `data/tmp/model-platforms-implementation/workflow-final.log`。
- 独立智能体完整回归：122 passed、1 skipped，耗时 42.42 秒；日志在其 `data/tmp/model-platforms-agent-final.log`。内置工具原有智能体与恢复专项：109 passed、3 skipped。
- 完整回归后补齐了冻结快照的实际调用、旧主控/写稿模型隔离、显式旧模型覆盖和 CLI namespace 修复。最终代码重新运行相关工作流专项：153 passed，12.59 秒；智能体内置共享模块/传输专项：49 passed，8.65 秒。完整回归数字不是声称最后这些补丁又跑过一遍全部测试。
- 最终 GUI 验证：工作流浏览器 1 passed，8.34 秒；独立智能体角色/API/浏览器合计 5 passed，7.52 秒。服务器、模型接口和数据均为隔离测试设施，测试结束后关闭。
- 两套 `npm run build` 均通过。既有 Typer/FastAPI/LangChain 弃用警告不等于测试失败。
- CLI 管理帮助确认包含全部 10 个子命令；9 个 Python 共享模块与 2 个共享前端文件逐项 SHA-256 一致，两边 `git diff --check` 通过。
- Git 忽略检查确认 `.env.gui`、模型配置、密钥密文及 HMAC 文件不进入普通 Git 添加；新增/修改源码的密钥字面量扫描未发现非合成密钥。这不等于保证仓库所有历史提交中没有密钥。

真实 OpenAI/Claude/其他厂商调用、真实费用、代理仅订阅策略及升级后兼容性尚未实测；本地测试不能替代这些证据。3 项 PostgreSQL 集成测试因其显式启用条件未满足而跳过，不报告为数据库实机通过。上述实施测试阶段没有提交或推送 GitHub；随后按用户要求执行交付前验证，见第 7 节。

## 6. 审查结论与边界

使用执行计划、测试驱动开发、系统调试及完成前验证技能；独立审查者确认了角色覆盖、费用过滤、压缩继承、环境凭据轮换、两文件 CAS 等缺口，逐项以失败用例复现后修复。最终定点复核确认已报告的重要问题均关闭；限定范围内没有剩余 Important。最后独立合成复验确认主控/写稿实际加载为两个不同模型，续跑中改变默认模型及地址仍保留原快照。

既有关键词、正则及 evidence.2 校准修改保留，不纳入无关回滚；本轮只接入模型解析和传输，不降低新闻事实/日期/查重/审核规则及发布权限。

## 7. GitHub 交付前验证

2026-10-07，用户要求上传两个仓库并备份旧 main。重新运行最终代码：工作流完整回归 1487 passed、8 skipped，425.94 秒；独立智能体完整回归 123 passed、1 skipped，45.25 秒；内置工具模型/智能体/恢复专项 113 passed、3 skipped，43.67 秒。两套前端构建通过。

两个仓库均已在 GitHub 建立 `backup/main-before-20261007-123730`：工作流对应 `6274704c6a01e1d86422acac37ff4d9fb9dffe7e`，智能体对应 `d5ce08a64f75ad6ac0b706660b97339612cc8ffb`。备份在更新 main 之前完成并读回远端分支验证，不使用强制推送。

提交范围仅代码、测试及本次三份公开设计/实施文档。暂存内容和已跟踪/待添加文件的密钥扫描通过，扫描没有输出密钥值；`.env.gui`、密钥密文、运行配置、浏览器 profile、生成记录、索引与日志未添加。此检查不代表所有历史提交均无密钥。GitNexus 已刷新并执行完整差异分析，报告 CRITICAL 共享调用风险；检测结果没有 partial/truncated 标记。图本身的静态分派和流程枚举边界仍存在，不将未报告流程视为不存在。
