# Volcengine Ark API Key

复制本文件为 `docs/volcengine_api-key.md`，填入你自己的火山方舟 API Key。

`docs/volcengine_api-key.md` 已被 `.gitignore` 忽略，不应提交到 Git。

```text
api_key="YOUR_ARK_KEY"
base_url="https://ark.cn-beijing.volces.com/api/v3"
region="cn-beijing"
```

也可以使用环境变量：

```powershell
$env:VOLCENGINE_API_KEY="YOUR_ARK_KEY"
$env:LLM_PROVIDER="volcengine"
$env:VOLCENGINE_LLM_MODEL="doubao-seed-2-1-turbo-260628"

$env:IMAGE_PROVIDER="volcengine"
$env:VOLCENGINE_IMAGE_MODEL="doubao-seedream-5-0-lite-260128"
$env:VOLCENGINE_IMAGE_SIZE="1440x2560"
```
