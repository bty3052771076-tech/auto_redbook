# LLM API Key (example)
#
# This file is for the fallback OpenAI-compatible provider.
# Primary LLM (Aliyun DashScope DeepSeek-V3.2) is configured via env:
#   ALIYUN_LLM_API_KEY (or ALIYUN_IMAGE_API_KEY / DASHSCOPE_API_KEY)
#
# Copy this file to `docs/llm_api-key.md` and fill in your own key.
# Make sure `docs/llm_api-key.md` is NOT committed.
#
# Used by `src/config.py` as an alternative to environment variables.
#
# Example:
# base_url="https://api.ppinfra.com/openai"
# model="deepseek/deepseek-v3-0324"
# api_key="YOUR_LLM_API_KEY"
base_url="https://api.ppinfra.com/openai"
model="deepseek/deepseek-v3-0324"
api_key="YOUR_LLM_API_KEY"
