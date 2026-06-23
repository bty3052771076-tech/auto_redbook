# Aliyun Bailian / DashScope image API key example

Copy this file to `docs/aliyun_image_api-key.md` and fill in your own key.

Do not commit `docs/aliyun_image_api-key.md`.

## Key and endpoint

```text
base_url="https://dashscope.aliyuncs.com"
api_key="YOUR_ALIYUN_BAILIAN_API_KEY"
region="cn-beijing"
```

The same key can also be provided with environment variables:

```powershell
$env:DASHSCOPE_API_KEY="YOUR_ALIYUN_BAILIAN_API_KEY"
# or
$env:ALIYUN_IMAGE_API_KEY="YOUR_ALIYUN_BAILIAN_API_KEY"
```

## Current GUI image models

The GUI exposes these Aliyun image models:

```text
wan2.7-image
wan2.7-image-pro
qwen-image-2.0-pro-2026-04-22
```

Default:

```powershell
$env:IMAGE_PROVIDER="aliyun"
$env:ALIYUN_IMAGE_MODEL="wan2.7-image"
```

If you want ordered fallback:

```powershell
$env:ALIYUN_IMAGE_MODELS="wan2.7-image,wan2.7-image-pro,qwen-image-2.0-pro-2026-04-22"
```

## Size and quality options

The project default size is a Xiaohongshu-friendly portrait ratio:

```powershell
$env:ALIYUN_IMAGE_SIZE="1104*1472"
```

For `wan2.7-image` and `wan2.7-image-pro`, Aliyun also supports `1K` / `2K`; `wan2.7-image-pro` supports `4K` in text-to-image scenarios. Use larger sizes carefully because generation can be slower and may consume more quota.

## Active example values

base_url="https://dashscope.aliyuncs.com"
api_key="YOUR_ALIYUN_BAILIAN_API_KEY"
region="cn-beijing"
