# 智能体与工作流：统一模型平台选择设计

日期：2026-10-07
状态：设计稿，待用户审阅；本次没有修改业务代码或执行模型测试。
适用程序：`redbook_agent`、`redbook_workflow`，包含 GUI、CLI、任务校准及断点续跑。

## 1. 目标、约束与成功标准

用户需要通过界面配置其他大模型平台的 API，也能自行添加供应商和模型。参考 opencodex 的设计，但不能让两套程序失去独立运行能力。

- 保留智能体主控、写稿、生图的独立绑定；更换主控不更换正文或图片模型。
- 自定义供应商必须能够实际调用，不仅保存和展示。模型名称不限定为内置列表。
- 同一厂商允许多个连接，区分地域、订阅、按量和不同凭据。
- GUI、CLI、校准、生成、压缩使用同一解析规则，执行后显示实际连接和模型。
- MiniMax 现有订阅配置保持可用，不要求再次同步额度；不能把订阅标为无限额度。
- 默认禁止自动进入按量付费，包括 PPInfra；明确选择其他收费平台时需要单独授权。
- 现有新闻时效、查重、事实审核、草稿确认、发布权限与上传串行规则不变。
- PostgreSQL 知识库、记忆和断点不降级；本设计不更换嵌入模型。
- 不在 C 盘安装东西；新增配置、密钥密文和测试产物放在 E 盘数据目录。

验收核心：自定义 OpenAI 兼容服务和至少一种原生协议服务，均可在对应角色完成最小真实调用；不跨角色、不越过费用授权、不泄漏凭据，旧脚本仍可使用。

## 2. 现状与实际缺口

下列结论来自本机文件，而非此前设计稿中的预期功能。

| 实际位置 | 当前行为 | 需要补齐的部分 |
| --- | --- | --- |
| 工作流 `apps/web_service.py:Workbench.save_provider/providers/models` | 可保存自定义连接、密钥和手动模型，但可选状态固定为“自定义供应商适配器尚未启用” | 从登记打通到可执行协议适配 |
| 工作流 `src/config.py:load_llm_configs` | 按 auto/aliyun/volcengine/siliconflow/minimax/ppinfra 分支解析 | 从连接与模型引用解析，不继续扩充厂商 if 分支 |
| 工作流 `src/llm/generate.py:generate_draft/generate_json` | LangChain 调用固定指定 `model_provider=openai` | 原生 Messages/Responses 等不能假装为 Chat Completions |
| 工作流 React `ModelPicker/ModelsPage` | 已有搜索、三角色和添加供应商，但自定义协议只有聊天/生图，目录和费用耦合 | 协议、能力、连接健康、费用分别建模 |
| 独立智能体 `backend/task_recognition.py:resolve_controller/call_model` | 校准白名单仅四家，发送固定 Chat Completions；包含 MiniMax 专用参数 | 校准复用运行时解析器和协议适配器 |
| 独立智能体 `backend/app.py`、`frontend/src/App.tsx` | 有连接信息与角色保存，缺少完整自定义连接 CRUD；顶栏固定 MiniMax 订阅 | 补齐管理入口，显示真实绑定 |
| `src/agent/editorial_agent.py:EditorialAgentConfig.validate` 及智能体工具副本 | 主控仍验证四家内置供应商 | 按所需操作能力验证，不按厂商名称判断 |

旧稿 `2026-09-17-model-roles-provider-management-design.md` 的独立角色、菜单和本地凭据约束继续有效。本稿补齐其未实现的通用运行时，并覆盖后来独立出来的智能体。

### 2.1 图分析范围

- GitNexus 绑定仓库 `auto_redbook` 和 `redbook_auto_agent`，索引时间为 2026-10-07 00:57 UTC；本轮及前轮未提交修改仍以实际文件核对，未宣称索引覆盖所有新代码。
- `load_llm_configs` 上游分析深度 2：风险 **CRITICAL**，5 个直接调用入口、12 个受影响符号、8 个受影响流程、4 个模块。包括新闻、AI资讯、福利、CLI 和上下文压缩，必须按高风险共享配置改造处理。
- 智能体 `resolve_controller` 风险 LOW，关联校准创建与采用候选计划；这不代表整个多协议改造为低风险。
- `save_provider` 返回 UNKNOWN；已核对 `apps/web_gui.py` 的 `/api/providers` 路由调用，不能当作无用方法或安全删除。
- 此次只新增文档。后续编码前重新做 impact；提交前执行完整 detect_changes，不以截断或局部结果代替完成检查。

## 3. opencodex 借鉴范围与方案选择

### 3.1 实际参考

本机安装包是 `@bitkyc08/opencodex` **2.73.0**；通过启动脚本和包元数据定位源文件，仅阅读公开源代码，未读取用户配置、账号池或密钥。

| 本机 opencodex 源文件 | 可复用的设计思想 | 本项目取舍 |
| --- | --- | --- |
| `src/types/provider.ts`、`providers/registry/types.ts` | 供应商、协议、端点、模型能力分别表达；支持模型级协议覆盖 | 使用较小的本项目配置契约，不照搬所有字段 |
| `providers/base-url-choices.ts` | 同厂商的地域、套餐端点分别配置 | 不凭厂商名推断订阅；原有地址不随升级自动替换 |
| `providers/model-discovery.ts`、`model-discovery-limits.ts` | 有界枚举、ID 验证、目录来源、供应商解析差异 | 统一发现接口，分页完整性明确；不把枚举成功当成推理可用 |
| `providers/model-presets.ts` | 常用模型与全量目录分开，用户选择不会被升级覆盖 | 收藏/已启用列表；不写死最新模型名称或默认勾选收费模型 |
| `providers/slug-codec.ts` | 界面标识和上游原生模型 ID 不能混淆 | 使用不透明本地 model_ref，原生 ID 原样传输，避免斜杠/冒号歧义 |
| `providers/key-store.ts`、`api-key-resolve.ts` | 配置保存引用，密钥另存；不可读取时失败关闭 | 引用属于本程序，不读取 opencodex 的凭据存储 |
| `config/provider-validation.ts` | 地址、认证头、协议和参数严格验证 | 认证从专用字段构造，禁止任意 Header 覆盖认证 |
| `config/atomic-write.ts`、`mutation-lock.ts` | 原子落盘、配置版本、跨进程写协调 | 借鉴一致性，不引入 opencodex 的 SQLite 锁数据库 |

项目公开说明介绍了供应商面板、OpenAI 兼容端点和多协议代理能力；本设计参考其组织方式，不承诺其全部平台在本软件已验证。[opencodex 项目](https://github.com/lidge-jun/opencodex)

### 3.2 方案比较

| 方案 | 优点 | 代价 | 决策 |
| --- | --- | --- | --- |
| 统一目录 + 本项目协议适配器，opencodex 可选 | 无代理也可运行，角色和费用可控，能接原生 API | 需实现有限的协议及契约测试 | **采用** |
| 所有请求强制走 opencodex | 多平台接入较快 | 额外进程、升级耦合、上游计费和路由不透明 | 不作为必需依赖 |
| 每增加厂商就增加 if/环境变量 | 首次改动小 | 校准、生成和选择器继续不一致 | 不采用 |

不复制账号池、订阅令牌、风控绕过、厂商登录模拟或账号轮换。HTTP API 支持与网页会员/订阅权限是不同概念，不能从一个推导另一个。

## 4. 模块与数据契约

### 4.1 模块边界

```text
GUI / CLI / 校准 / 压缩 / 业务生成
                  |
         ModelResolutionService
            |              |
     ProviderRegistry   BillingPolicy
            |              |
     CatalogService -> CapabilityValidator
                  |
         RunModelSnapshot
                  |
        RuntimeClientFactory
                  |
    协议 Adapter -> HTTP transport + CredentialStore
                  |
         规范化结果 / 结构化错误
```

- `ProviderRegistry`：连接、模型、默认角色、配置版本；不发起生成。
- `CatalogService`：发现/手动录入/目录差异；不根据价格目录宣称用户有免费额度。
- `ModelResolutionService`：解析本次覆盖与默认绑定，返回运行快照和拒绝原因。
- `CapabilityValidator`：按调用目的验证文本、结构化输出、工具或视觉能力。
- `BillingPolicy`：验证本次计费授权、费用证据和允许回退列表。
- `RuntimeClientFactory`：创建角色级客户端，隐藏密钥；禁止并发修改全局 `os.environ`。
- `Adapter`：编解码本协议及完成状态；不能改变业务审核结果或发布权限。

统一结果包含最终文本、工具调用、usage、完成原因、请求标识及供应商元数据；内部推理单独处理，不作为正文或聊天进度转发。沿用既有 LangChain 组件处理已验证协议，通过客户端工厂隔离创建；不再引入第二套任意工具执行器。图片结果保持独立类型。

建议协议层归入 `src/model_platforms/`；工作流和智能体内置 `tools/redbook_tools/src/model_platforms/` 使用同一版本代码和一致性测试。智能体不 import 旧工作流绝对目录，不调用全局 npm 包内部模块。

### 4.2 数据对象

| 对象 | 必需信息 | 关键规则 |
| --- | --- | --- |
| ProviderConnection | 不透明 connection_id、vendor_preset、名称、enabled、adapter、base_url、端点路径、auth_mode、credential_ref、revision、限流组、网络策略 | 名称可改，ID 不随改名变化；同厂商可多连接 |
| ModelEntry | 不透明 model_ref、connection_id、upstream_model_id、展示名、协议覆盖、目录来源、可见/启用、能力证据、参数、context/output 上限 | ID 原样传给上游，不能从展示名恢复 ID |
| CapabilityEvidence | 能力名、supported/unsupported/unknown、来源、时间、连接/模型修订、验证范围 | 声明、官方文档和真实调用分开显示；不从名称猜识图 |
| BillingEvidence | free/subscription/payg/unknown、适用模型/端点/凭据修订、来源、有效期、余额与单位、仅订阅是否可强制 | 用户选择“订阅”只是声明，不能伪装平台确认 |
| RoleBindings | agent、writer、image；可选 vision_review；默认值与本次覆盖分开 | 校准与压缩默认继承 agent，不能悄悄继承 writer |
| RunModelSnapshot | 各角色解析结果、连接/模型修订、adapter 版本、参数、费用授权、回退白名单、凭据引用及修订、限流组 | 无密钥；任务确认及启动后冻结 |
| ProviderCheckResult | check_id、检查类型、开始/结束时间、结论、脱敏错误、已测能力、费用提示 | 不能将目录 200 显示为全部能力正常 |

旧 `provider:model` 标识仅在迁移边界解析一次并映射到 model_ref。模型本身可能包含 `/`、`:`、版本号，不能再次 split 后丢失内容。opencodex 返回的路由 selector 原样存为该代理连接的 upstream_model_id，不自行编码或还原斜杠。

### 4.3 独立存储与共享

- 智能体默认：`E:/AI/codex/redbook_runtime/data/model_platforms/`。
- 工作流默认：`E:/AI/codex/redbook_workflow/data/model_platforms/`。
- 非秘密技术配置采用版本化 `registry.json`；凭据密文位于相邻 `secrets/`，不与配置混写。
- 两套程序使用相同契约、默认独立配置。需要共用时，用户显式指定同一 E 盘配置目录；agent/workflow 角色默认绑定按 namespace 分开。
- 配置更新用跨进程 OS 文件锁 + expected_revision/CAS + 同目录原子替换；两端同时编辑过期版本返回 409，不以最后写入覆盖。
- 密钥先写入不可变 revision 并验证可读，再原子发布引用；发布失败保留旧连接，仅清理无引用的新密文。删除需核对运行快照引用。
- 智能体计划、证据和运行快照继续进入现有 PostgreSQL；JSON 仅为技术配置，不代替 PostgreSQL 知识库、记忆、运行状态或恢复机制。
- 新模块不能要求人工脚本必须启动独立智能体 Web 服务；正常配置读取和运行仍在本地进程内完成。

## 5. 平台与协议接入范围

### 5.1 对用户开放的连接入口

平台列表由版本化 preset 数据驱动，不写死在 React 菜单或校准白名单。

| 入口 | 本轮设计支持范围 | 边界 |
| --- | --- | --- |
| 既有 MiniMax、百炼、火山引擎、硅基流动 | 保留原有连接，迁移到共同目录 | 不强制重填密钥、换端点或刷新额度 |
| OpenAI API | Chat Completions / Responses 连接模板 | API 连接的费用授权与 ChatGPT 会员分开 |
| DeepSeek、智谱/Z.AI、Moonshot/Kimi、xAI、OpenRouter 等 | 使用经官方文档核对的兼容协议模板；不能假设每个模型能力相同 | 新模板默认未验证，不预填“免费” |
| Anthropic/Claude API | 原生 Messages 协议 | 不把 Claude 网页订阅当作 API Key 额度 |
| Gemini API | 优先官方 OpenAI 兼容接口；原生 generateContent 提供独立 adapter | 协议能力和可选参数需分别验证 |
| Ollama / 本地兼容服务 | 本机 OpenAI 兼容协议，无认证或显式本地认证 | 只允许明确的本机目标，不继承远程 API Key |
| 自定义平台 | 手动名称、API 基址、已实现协议、认证和模型 | 不支持的协议明确不可选；无枚举接口也可手动录入 |
| opencodex 连接 | 用户指定的本地代理，Chat/Responses 已支持接口 | 可选外部服务，不读取其私有配置，不控制其账号池 |

官方文档已确认 Gemini 提供兼容 API 基址及模型列表，Ollama 只覆盖 OpenAI API 的子集，说明“同为兼容”不能代替能力验证。[Gemini 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[Ollama 兼容范围](https://docs.ollama.com/api/openai-compatibility)

DeepSeek 提供兼容调用格式；百炼的地域/业务空间需要体现在连接配置，不能用一条通用地址覆盖所有账户。[DeepSeek 接入说明](https://api-docs.deepseek.com/guides/codex)、[百炼 API Key 与地域配置](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key)

具体模型以用户接口返回或人工录入为准，不在本设计写死未来“最新模型”。其他模板需在后续实施时核对其官方协议、地址及认证规则，未核对项不以预设可用状态发布。

### 5.2 必需适配器

| adapter | 生成端点 | 最小交付 | 注意事项 |
| --- | --- | --- | --- |
| openai_chat | API 基址 + `/chat/completions` | 文本、结构化文本、函数调用、可验证的视觉输入 | 区分 max_tokens/max_completion_tokens，按能力发送 response_format |
| openai_responses | API 基址 + `/responses` | 文本/工具输出，明确终止和 usage | 不依赖 previous_response_id 才能恢复；不把 reasoning 当正文 |
| anthropic_messages | API 基址 + `/messages` | system、文本/图像块、tool_use/tool_result、stop_reason | 认证与版本头由模板配置，不能按 Chat 格式解析 |
| gemini_generate_content | API 基址 + 相对模型资源路径 | contents/parts、systemInstruction、functionCall、finishReason | 原生认证独立，模型 API 名称原样映射，忽略非正文 thought |
| existing_image | 保留 MiniMax/opencodex 等现有实现 | 文生图、已支持编辑和双图编辑 | 不随 LLM 目录迁移重写现有图片链路 |
| openai_image | 基址 + images/generations 或 edits | 对已验证服务规范化图片结果 | 编辑与生成能力分开，支持格式通过专用验证而非名称判断 |

Anthropic 的 Messages 与模型枚举分别有官方接口；OpenRouter 的目录提供能力、价格等字段，但价格不代表当前用户拥有额度。[Claude API 概述](https://platform.claude.com/docs/en/api/overview)、[Claude 模型列表](https://platform.claude.com/docs/en/api/models/list)、[OpenRouter 模型目录](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)

首个可交付版本必须包含自定义 Chat、Responses、Messages、Gemini 兼容接入以及本机兼容连接；原生 Gemini 属于同一设计的第二阶段，不在第一阶段 GUI 标为已实现。旧生图服务保持运行；新自定义生图只有通过相应 adapter 测试后才显示可执行。

### 5.3 地址和参数

- 基址保留原有 `/v1`、`/api/v3`、`/compatible-mode/v1` 等前缀；不全局删除或追加版本段。
- 默认相对端点以基址为前缀追加；模型级覆盖只允许明确的协议及相对路径，不改变认证目标 origin。界面显示计算后的请求地址预览。
- 用户误填完整 `/chat/completions` 等生成端点时提示迁移到“基址 + 路径”并让用户确认，不静默修正。
- 超时区分连接、响应读取和单次总上限，不再使用所有任务共用的时间预算。
- 每模型配置可选的 temperature、top_p、输出 token 上限、推理强度和缓存参数；只有 adapter 支持的字段可编辑，未知参数不得透传。
- 原有新闻字数、评价长度、时效及引用提示词不因换平台消失；token 上限与中文字数不是同一个约束。
- 兼容差异由 Connection/Model 参数声明处理，不再用模型名正则无条件推断 temperature 或 reasoning 支持。

## 6. 模型发现、额度和可执行性

### 6.1 模型目录

“更新模型列表”“检查连接”“测试调用”“同步额度”是四个独立命令，进入页面或点击模型选择器不触发它们。

- 发现操作总预算默认 30 秒、最多 4 MiB 解压后数据、2000 条、20 页；到上限标记 partial，不算完整目录。单连接刷新合并重复请求。
- OpenAI 兼容模型目录默认相对 `models`；原生协议按 preset 使用其分页和名称字段。用户自定义发现路径只允许同 origin 的安全相对路径，无任意解析脚本。
- 无枚举接口/404 不等于连接不可用，允许手动添加模型并做对应能力测试；公开目录 200 不等于认证通过。
- 完整权威目录成功后，自动发现模型的缺失状态标为 catalog_missing，不物理删除；新任务提示重新验证，不自动替换绑定。
- 目录为空、partial、超时、401 或失败保留 last_known_good；界面显示本次失败，不能伪装为同步成功。
- 手动模型和收藏不被刷新删掉；catalog_missing 模型真实调用验证成功后可人工保留，明确标为人工确认。
- 模型新增默认进入未启用列表，不自动选为默认，不因同名展示名合并不同连接。

### 6.2 三个独立状态

每个模型分别显示：目录是否有它、当前连接是否能完成所需操作、费用策略是否允许使用。不再用剩余额度一个字段决定全部状态。

对操作 o，执行许可为：连接启用 + 凭据可解析（或本机无认证）+ adapter 实现 o + 所需能力证据有效 + 计费授权满足 + 未处于硬封禁/熔断。

- 未测试连接可保存、可查看，但执行前需要相应最小调用验证；一次验证只证明此次操作，不证明永远可用。
- 自定义模型先通过纯文本测试可用于写稿；校准/主控额外通过所需结构化输出测试。
- 当前受控编排只要求结构化规划时，不强制工具调用；真正调用 tools 的主控必须完成一次无副作用工具回环测试，校验工具参数和结果关联。
- vision_review 要求视觉输入及有效评价结构；LLM 具有识图能力也不等于能生图。
- 验证键包括连接 origin/路径、adapter 版本、模型 ID、凭据 revision；修改任何一项将相关验证置为待复核。
- 暂时性 429/超时与永久能力不支持分开；健康记录默认可缓存 24 小时，不能把 24 小时设为所有订阅的额度强制重同步周期。

### 6.3 费用策略

1. 默认“仅已授权免费/订阅”：保留当前 MiniMax、已验证免费模型和已授权图片订阅；不自动查询、刷新或变更用户套餐。
2. 新连接的 free/subscription 字段是用户声明。能确认额度或仅订阅端点时保存证据；无法确认时显示“费用未验证”，不能自动进入免费池。
3. 可授权“指定 API，允许按量”：用户主动选择连接、角色、费用范围和有效期后才允许调用。校准结果、提示词和失败回退不能扩大该授权。
4. 费用未知或代理无法解释上游路由时，默认阻止自动执行；用户可以明确承担该连接的费用风险，不能显示为零费用保证。
5. 对会从订阅扣完后继续使用余额的服务，若没有可强制的 subscription_only 边界，显示限制并禁止声称不会花余额；不得用“额度充足”代替技术证据。
6. 有可靠价格时采用预扣预算 + 实际 usage 对账；价格未知时不声称金额硬上限可保证，可限制请求/token 数并显示金额不可估计。人民币/美元/次数/token 不混比。
7. 回退白名单按角色配置，默认仅原连接重试；PPInfra 默认关闭。收费回退必须额外、明确授权，不能借用全局旧 ALLOW_PAID_LLM_FALLBACK 值扩权。

订阅资格还要匹配模型、端点和允许的使用场景；某套餐允许编码客户端调用，不能据此默认允许任意新闻生产 API 用途。新订阅模板必须核对厂商约束并显示适用范围；不靠改协议或更名绕过套餐边界。

## 7. GUI 设计

保留现有页面风格和业务布局，只统一连接与选择区域；不重做新闻工作流或导航体系。本次为交互规格，没有修改 Pencil 画布或制作可交互原型。

### 7.1 入口及页面

- 独立智能体“连接与模型”增加“供应商 / 模型目录 / 默认角色”三个标签；顶栏显示当前主控的实际连接名称，不固定写 MiniMax。
- 工作流“模型与供应商”沿用相同三标签和字段。额度仍可按平台查看，但模型身份来自统一目录。
- 对话输入区旁增加主控选择器和“本次模型”入口；计划侧栏列出主控、写稿、图片方式及实际模型，用于执行前核对。
- “大模型校准”默认显示并使用当前对话主控；允许在其菜单中为此次校准单独选择已验证的模型，不能更改生成角色默认值。校准记录保存所用 model_ref。
- 自动发帖显示本次写稿/生图，使用智能体页面才显示主控；材料发帖只显示实际参与的角色。CLI 相同角色字段，不要求 GUI 先启动。

### 7.2 模型菜单

```text
主控模型 [我的 MiniMax 订阅 / 模型展示名       v]

展开：
[搜索供应商或模型 ID]           [仅可执行]
最近使用 / 收藏
我的 MiniMax 订阅
  模型名称               订阅已授权 · 文本 / 结构化
  完整模型 ID            上次验证时间
我的 DeepSeek API
  模型名称               按量 · 未授权（禁用原因）
我的本地模型
  模型名称               本机 · 文本 / 工具已验证
自定义连接
  手动模型               尚未测试（测试调用入口）
------------------------------------------------
[+ 添加供应商]                         [管理模型]
```

- 三角色菜单共用数据与可执行原因，按实际操作能力筛选；不显示虚构“最强/最快”档位。
- 已选模型用勾选；长名称自然换行，完整 ID 可复制，不修改实际 ID。
- 禁用项可查看原因和到达修复入口，不静默隐藏所有候选，让空菜单可解释。
- 不因目录排序变化而更换选择；自动策略只在用户选择“自动（已授权候选）”时使用。
- 移动端采用全宽弹层；按钮和文本不互相遮挡。键盘可选择、退出、返回焦点。

### 7.3 添加供应商流程

| 步骤 | 用户输入/动作 | 系统反馈 |
| --- | --- | --- |
| 1 选择类型 | 厂商模板 / 自定义 API / 本机服务 / opencodex | 列出已实现协议，订阅/按量选项分开 |
| 2 配置连接 | 名称、地域/套餐、基址、协议、认证、Key | 请求地址预览、凭据仅本地保存；保存不发生成请求 |
| 3 添加模型 | 更新目录或手动输入 ID/展示名 | 目录来源、能力待验证；可收藏与启用部分模型 |
| 4 验证用途 | 文本 / 结构化规划 / 工具 / 识图 / 生图 | 每项显示可能费用、执行时间和具体检查范围 |
| 5 授权并绑定 | 费用策略、角色、默认或仅本次 | 能力和费用不足时解释，符合才可执行 |

高级项包括安全相对路径、认证方式、白名单静态头、代理模式、超时、限流和参数。密钥输入留空保留旧值；“清除”“替换”独立命令，不把掩码当密钥发回。

测试按钮区分“检查连接”和“测试调用”；测试调用需要用户明确点击，并且先完成适用费用授权。最小测试不读新闻数据、不访问平台、不上传草稿，生图测试返回可查看的本地产物。

### 7.4 任务冻结与异常

- 保存默认值只影响新任务；执行确认前重新解析并冻结快照，避免采用旧校准后变成其他模型。
- 设置改变导致校准指纹失效时，保留原计划，提示重新校准或选择原版本；不得自动采用新计费来源。
- 运行页实时显示角色、连接、模型、协议、排队/请求/重试、耗时、限流原因；不显示密钥或内部推理正文。
- 断点恢复继续原 model snapshot；凭据撤销则等待补充授权，同身份轮换密钥可显式创建续跑版本，仅重做未完成项。
- 删除/停用被运行任务引用的连接须先取消或显式重配；收藏和默认绑定也显示受影响位置。

## 8. API、CLI 和校准对接

### 8.1 后端契约（拟新增，当前并非已有接口）

两套后端实现同一 v2 DTO；不直接把 HTTPX/LangChain 配置或密钥发给 React。

| 接口 | 职责 |
| --- | --- |
| GET `/api/model-platforms/presets` | 已实现模板、协议、非秘密字段与文档链接 |
| GET/POST `/api/model-platforms/connections` | 连接列表 / 新建；POST 带幂等键 |
| GET/PATCH/DELETE `/api/model-platforms/connections/{id}` | 详情、带 expected_revision 的修改、引用检查删除 |
| PUT/DELETE `/api/model-platforms/connections/{id}/credential` | 替换/清除凭据；不提供读取密钥接口 |
| POST `/api/model-platforms/connections/{id}/discover` | 有界发现，返回 operation_id、完整性和差异 |
| GET/POST `/api/model-platforms/models` | 模型目录及手动添加 |
| GET/PATCH `/api/model-platforms/models/{model_ref}` | 单模型详情、启用/收藏/能力声明 |
| POST `/api/model-platforms/checks` | 授权后按指定操作测试，返回 operation_id |
| GET `/api/model-platforms/operations/{id}` | 检查进度、脱敏错误和已验证范围 |
| GET/PUT `/api/model-platforms/roles` | namespace 的默认角色，修订冲突检查 |
| POST `/api/model-platforms/resolve` | 无生成副作用，校验本次角色、策略及所需能力 |

所有修改已有资源的请求要求 expected_revision，分页响应包含 cursor、complete、catalog_revision，不能以一个截断页面决定下架。

旧 `/api/providers`、`/api/model-bindings`、`/api/model-roles` 与 connections 模型字段由兼容投影提供；前端先迁移到 v2，旧入口在原语义下继续使用。v2 错误字段为 code、role、connection_id、model_ref、retryable、action、operation_id，不返回原始凭据或完整上游错误体。

兼容投影保留已迁移条目的旧模型 ID，并通过持久化映射转换到 model_ref；新版不要求旧前端理解 UUID。原有免费/订阅脚本保持运行；旧脚本中的全局收费回退标志不再视为无限授权，首次迁移必须转换为用户确认的连接级费用授权，否则明确提示配置冲突。

### 8.2 CLI

未来增加统一的 model-platforms 管理子命令：list、add、models、discover、check、roles、resolve。模型测试只在显式 check 时发起。

- 生成命令新增 `--writer-model-ref`、`--image-model-ref`；智能体命令新增 `--controller-model-ref`，以及单独的费用授权引用。
- 旧 `LLM_PROVIDER`、`MINIMAX_*` 等继续可用，但只在缺少明确本次 model_ref 时导入为 legacy connection。
- 配置优先级：任务显式引用 > namespace 默认绑定 > 旧配置导入结果；回退只走已授权列表，不随环境变量扩张。
- 不允许 API Key 作为命令行参数进入进程列表。使用 GUI 凭据输入或指定环境变量引用。
- 自定义连接不存在、协议未实现、能力/费用不满足时在生成之前失败，告诉用户具体修复入口。

### 8.3 大模型校准及主控

- `resolve_controller` 改为统一 resolver 的薄入口，不保留四厂商 fields 字典；`call_model` 使用当前角色 adapter。
- 校准解析源为“此次校准显式覆盖 > 当前对话待确认计划的主控 > namespace 主控默认”；记录冻结相同解析来源和修订，采用时验证同一快照，不能改回只读全局默认的旧逻辑。
- 保留 `task-recognition.v2` 用户任务 schema 和 evidence.2 引用验证；平台适配只负责获取最终文本，不修正、伪造或放宽用户证据。
- 上游结构化 schema 支持未知时，采用受验证的提示词 JSON 路径及本地 schema 校验；不把普通文本转成“校准成功”。
- 用户指定平台名称时只匹配已授权连接；同名多连接必须澄清具体连接，不能猜订阅/按量端点。
- 模型输出只能提出可选 model_ref，不得写入 API 地址、认证、价格、授权和并发策略。
- 主控规划、工具回环、压缩均通过统一运行时；更换协议时重新编译规范化对话，不跨供应商复用 previous_response_id、思考签名或私有工具状态。

## 9. 安全、稳定性与效率

### 9.1 凭据和网络

- Windows 默认使用当前用户 DPAPI 加密，密文文件保存在 E 盘；服务迁移需要明确重新配置或安全迁移，不承诺密文换机器即可解密。
- 服务器提供环境变量 secret_ref 或受权限保护的加密存储；解密材料由部署环境注入，不与密文一起提交。不可解密时拒绝，不退回明文。
- Key 输入可被本地后端保存，但 GET 响应、PostgreSQL 快照、日志、导出、测试截图、备份包中不包含明文。使用现有会话认证、CSRF/origin 校验，跨站请求仍拒绝。
- API 基址禁止 userinfo、查询密钥、fragment；认证头由专用字段生成。高级头禁止 Authorization、Cookie、Proxy-Authorization、x-api-key 等认证覆盖，敏感的额外凭据用 secret_ref。
- 公网连接 HTTPS 且验证 TLS；拒绝不安全跳转和跨 origin 转发认证。默认拒绝私网/链路本地/云 metadata、IPv6 等价目标和 DNS 重绑定。
- 本机模式仅允许明确 loopback 地址和端口；内网服务需要独立批准的目标 allowlist，不让任意对话创建目标。
- 代理策略每连接选择继承系统 / 直连 / 指定代理；loopback 默认直连。代理凭据另存，不在诊断里打印代理 URL 密码。
- 加载地址改变时重新授权认证目标，不能将旧 Key 因同名 preset 升级而发送到新域名。
- opencodex 集成只访问用户配置的公开模型接口。代理若可自动换到收费上游，必须有可验证的仅订阅路由配置/独立连接约束；本程序没有证据时不能保证“不切换付费”。代理更新后重新做契约检查，不依赖其 npm 内部函数或 C 盘配置文件。

### 9.2 限流和恢复

- 保持 LLM 与生图独立工作队列，平台上传继续串行；校准也计入同连接 LLM 配额，不能用另一个线程池绕过。
- 通用 LLM 初始上限 2，MiniMax 保留已配置的最多 5；生图保留当前最多 2。其他平台可由用户设置并发，实际受连接/账号限流组、角色队列和已验证限制的最小值约束。
- 相同凭据/配额账户的不同连接可显式共用 rate_limit_group，避免换名称就突破限制；共用目录由一个应用取得生成运行租约，另一端可编辑与读取但不能另起同限流组任务。多主机并发另用 PostgreSQL 协调，不宣称本地文件锁能限流多机器。
- 有界重试仅在 adapter/策略准许时进行，遵循 Retry-After，默认最多 2 次额外请求；显式记录代理内部重试可见性，防止两层无界倍增。
- 401/403 等凭据问题立即等待修复；429 分清速率与额度；输出达到上限、拒绝、安全终止、未完成流分别报告，不当作正常完整内容。
- 不默认重放已经返回部分输出但结果不确定的调用；费用/副作用状态标为 unknown。工具参数解析失败不得触发工具或发布动作。
- 熔断后保留已完成稿件、图片和断点，用户修复后仅继续未完成项；不让某平台失败造成整批内容重跑。

### 9.3 自动选择与速度

- 默认人工固定模型，显式自动模式仅在角色已授权候选集合内挑选。
- 先过滤能力、费用和可用性，再根据该角色实测成功率、p50/p95 延迟、吞吐及可比较的额度比例排序；不能直接比较不同单位剩余量，不凭厂商品牌估计能力分。
- 用户能力等级属于偏好；本项目任务测试结果是证据。无实测数据标为未知，不能假造综合评分。
- 菜单读取缓存，不调用所有厂商；客户端按快照复用、配置修订失效，不为每篇稿件探测模型目录。
- 性能验收只承诺测量，不预报尚未测试的提速数。区分目录、排队、模型首响应、总生成、审核和平台串行耗时。

## 10. 迁移边界与实施分层

本节用于确定模块交付边界，不是已经完成的代码或测试结果。

1. 配置契约、凭据引用与兼容投影：从 `.env.gui`、旧 providers.json 导入，预览差异；不覆盖原文件、不取消旧默认、不在启动时做网络测试。
2. 接通自定义 Chat、Responses、Messages 和 Gemini 兼容连接，统一主控/校准/写稿/压缩的客户端；以旧配置回归通过作为转入新运行时的门槛。
3. 两套 GUI/CLI 管理与角色选择：目录更新、手动添加、能力测试、费用授权、错误修复、运行快照与实际调用显示。
4. 补齐原生 Gemini 与经过产物验证的自定义生图；本机 opencodex 接入作为可选连接做契约检测，不更新、停止或重配用户现有代理。

旧标识能唯一映射时迁移；歧义、无效模型和未实现协议保留为不可执行条目，要求用户选择，不自动切到收费或其他厂商。旧任务保持原快照；仅新任务使用新的默认。

对应改造位置：工作流 `apps/web_service.py`、`apps/web_gui.py`、`apps/cli.py`、`apps/gui.py`、`frontend/src/main.tsx`、`src/config.py`、`src/llm/generate.py`、`src/agent/compaction.py`、`src/agent/editorial_agent.py`；智能体 `backend/app.py`、`backend/task_recognition.py`、`frontend/src/App.tsx`、`frontend/src/api.ts` 及其自带工具副本。无需改写新闻采集、平台上传和 PostgreSQL RAG 实现。

## 11. 验证与验收矩阵

| 编号 | 验证场景 | 必须确认 |
| --- | --- | --- |
| V01 | 三角色绑定三个不同连接，校准与压缩继承主控 | 实际 HTTP 请求与快照一致，无角色串用 |
| V02 | 两个同厂商订阅/按量连接 | 无默认端点偷换，密钥/限流/费用分开 |
| V03 | 自定义模型含 `/`、`:`、长 ID、同展示名 | 上游 model 原样，引用无歧义；桌面/390px 不溢出 |
| V04 | 手动模型，没有 `/models`、公开目录忽略 Key | 不误判不可用或认证成功；最小调用可验证 |
| V05 | 模型新增/下架、分页中断、空目录、重定向 | 完整性正确，失败不删目录/默认/人工条目 |
| V06 | Chat/Responses/Messages/Gemini 兼容 fixture | 对应认证、system、text、tools、usage、终止正确 |
| V07 | 不支持 temperature/schema、token 截断、thinking 输出 | 不发送禁止参数、不混入思考、不接受残缺文本 |
| V08 | 主控真实无副作用工具回环、非法工具参数 | 正确关联 call/result；非法参数无执行副作用 |
| V09 | 旧 evidence.2 校准及关键词回归 | 已修复混合引用仍通过，伪造引用仍拒绝 |
| V10 | 未授权收费、订阅耗尽、代理上游费用未知 | 阻止收费回退，错误可操作，无静默同步额度 |
| V11 | 同时校准/写稿/生图、429/401、跨进程争写配置 | 连接预算有效，限流不被绕过；409 不丢修改 |
| V12 | 并发任务配置冻结、旋转/撤销 Key、重启续跑 | 保留成果，明确重配，只执行未完成项 |
| V13 | SSRF、loopback/私网误用、跨域跳转、恶意头 | 请求未发送到禁止目标，认证不泄漏 |
| V14 | GET/错误/日志/导出/Git 候选 diff 扫描 | 合成测试密钥不出现在任何公开投影 |
| V15 | 旧环境变量脚本及两套程序独立运行 | 旧工作流移走时智能体可运行；智能体未启动时 CLI 可运行 |
| V16 | GUI 添加、手动模型、测试、绑定、取消及页面刷新 | 用户能闭环配置，取消无副作用，实际绑定可持久化 |
| V17 | 自定义视觉/生图与双图编辑 | 图片解码及实际产物合格，识图不冒充生图，旧图片链路不退化 |
| V18 | opencodex 当前版本及升级后的公开接口契约 | 不依赖内部包路径，服务不可用有明确错误，不接管账号池 |

测试分层：纯契约/MockTransport 单测 -> 两套本地 API 与 GUI 交互 -> 用户授权后的最小真实 API 调用 -> 仅在用户另行要求时验证新闻生成与平台草稿。真实 API 测试记录连接类型、模型、费用授权、p50/p95 与耗时，不把模拟结果算作平台实测。

密钥保护验收使用合成 canary，不读取或输出实际 API Key；Git ignore 检查不能代替对已跟踪文件和暂存内容的扫描。新数据默认放在忽略的 data 目录，公开示例只有空引用。生成记录和项目文档保留。

## 12. 本次设计验证与交付状态

- 已阅读两套程序的实际供应商、角色、校准、生成、限流实现及旧设计。
- 已阅读本机 opencodex 2.73.0 的公开实现并核对项目与部分厂商官方文档；不同版本不视为同一份已验证协议。
- 本次只新增本设计文档及智能体目录内的同版副本；没有更改业务代码、配置、Key、运行中的服务或原设计稿。
- 没有安装依赖、读取用户 opencodex 配置/账号池、同步额度、调用模型、生成内容、上传、发布或推送 GitHub。
- 上表是后续验收要求，不是本次已执行并通过的测试；设计文件完成后做格式、链接、内容一致性和工作树范围检查。

## 13. 参考资料

本机 opencodex 源码根目录：`C:/Users/30527/AppData/Roaming/npm/node_modules/@bitkyc08/opencodex/`，仅只读参考。

- [opencodex 公开仓库与供应商面板](https://github.com/lidge-jun/opencodex)
- [opencodex 供应商数据契约](https://github.com/lidge-jun/opencodex/blob/main/src/types/provider.ts)
- [opencodex 模型发现](https://github.com/lidge-jun/opencodex/blob/main/src/providers/model-discovery.ts)
- [opencodex 密钥引用存储](https://github.com/lidge-jun/opencodex/blob/main/src/providers/key-store.ts)
- [opencodex 地址与 Header 验证](https://github.com/lidge-jun/opencodex/blob/main/src/config/provider-validation.ts)

以上 main 链接用于定位公开模块，可能随项目更新变化；本设计的代码判断以本机 2.73.0 文件为准。厂商 API 链接已附在相关设计段落；未核对的新预设需在实施时补充官方证据。
