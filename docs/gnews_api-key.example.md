# GNews API Key 示例

复制本文件为 `docs/gnews_api-key.md`，填入你自己的 GNews API Key。

`docs/gnews_api-key.md` 已被 `.gitignore` 忽略，不应提交到 Git。

```text
api_key="YOUR_GNEWS_API_KEY"
base_url="https://gnews.io/api/v4"
```

也可以不创建文件，直接使用环境变量：

```powershell
$env:GNEWS_API_KEY="YOUR_GNEWS_API_KEY"
$env:GNEWS_LANG="en"
$env:GNEWS_COUNTRY="us"
```
