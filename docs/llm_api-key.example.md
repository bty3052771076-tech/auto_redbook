# LLM API Key example

This file is for the fallback OpenAI-compatible provider, currently ppinfra.
Copy it to `docs/llm_api-key.md` and fill in your own key.

Do not commit `docs/llm_api-key.md`.

## ppinfra fallback

```text
base_url="https://api.ppinfra.com/openai"
model="deepseek/deepseek-v3-0324"
api_key="YOUR_LLM_API_KEY"
```

The same values can also be provided with environment variables:

```powershell
$env:LLM_PROVIDER="ppinfra"
$env:LLM_BASE_URL="https://api.ppinfra.com/openai"
$env:LLM_MODEL="deepseek/deepseek-v3-0324"
$env:LLM_API_KEY="YOUR_LLM_API_KEY"
```

## Aliyun / DashScope primary LLM

Aliyun is configured with environment variables or `.env.gui`, not this fallback file:

```powershell
$env:LLM_PROVIDER="aliyun"
$env:DASHSCOPE_API_KEY="YOUR_DASHSCOPE_KEY"
$env:ALIYUN_LLM_MODEL="qwen3.7-plus"
```

Supported Aliyun free-model options are documented in:

```text
docs/模型与GUI供应商配置.md
```

## Active example values

```text
base_url="https://api.ppinfra.com/openai"
model="deepseek/deepseek-v3-0324"
api_key="YOUR_LLM_API_KEY"
```

base_url="https://api.ppinfra.com/openai"
model="deepseek/deepseek-v3-0324"
api_key="YOUR_LLM_API_KEY"
