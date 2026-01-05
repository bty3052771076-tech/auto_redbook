# DeepSeek V3（0324）在本项目中的配置示例

本项目的 LLM 调用走 **OpenAI-compatible** 接口（见 `src/llm/generate.py`），因此只需要正确配置：
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

## 1) 在本项目中配置（推荐）

方式 A：环境变量（最安全，不落盘）

```powershell
$env:LLM_API_KEY="YOUR_DEEPSEEK_API_KEY"
$env:LLM_BASE_URL="https://api.ppinfra.com/openai"
$env:LLM_MODEL="deepseek/deepseek-v3-0324"
```

方式 B：本机文件（不要提交到仓库）

复制 `docs/llm_api-key.example.md` 为 `docs/llm_api-key.md`，内容示例：

```ini
base_url="https://api.ppinfra.com/openai"
model="deepseek/deepseek-v3-0324"
api_key="YOUR_DEEPSEEK_API_KEY"
```

## 2) DeepSeek 官方 Python 调用示例（OpenAI SDK）

> 仅用于对照你自己的可用性；本项目内部会通过 LangChain 的 OpenAI-compatible client 调用。

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://api.ppinfra.com/openai"),
)

resp = client.chat.completions.create(
    model=os.getenv("LLM_MODEL", "deepseek/deepseek-v3-0324"),
    messages=[
        {"role": "system", "content": "你是一个小红书文案助手，用中文写作。"},
        {"role": "user", "content": "给我 3 套通勤简约冬日穿搭思路。"},
    ],
)

print(resp.choices[0].message.content)
```

## 3) 在本项目中运行（示例）

生成并保存草稿：
```powershell
.\.venv\Scripts\python -m apps.cli auto --title "冬日穿搭" --prompt "通勤简约风，给我3套搭配思路" --assets-glob "assets/pics/*" --login-hold 600
```
