# Juhe API Key Example

This is a template only. Do not put real API keys in this example file.

To use a local key file, copy this file to `docs/juhe_api-key.md` and fill in your own values.
`docs/*api-key.md` is ignored by git in this repository.

```ini
# News headline API: https://www.juhe.cn/docs/api/id/235
news_appkey="YOUR_JUHE_NEWS_APPKEY"

# Finance news API: https://www.juhe.cn/docs/api/id/743
finance_appkey="YOUR_JUHE_FINANCE_NEWS_APPKEY"

# Optional overrides.
news_base_url="https://v.juhe.cn/toutiao"
finance_base_url="https://apis.juhe.cn/fapigx/caijing"
```

PowerShell environment-variable alternative:

```powershell
$env:NEWS_PROVIDER="juhe"
$env:JUHE_NEWS_APPKEY="YOUR_JUHE_NEWS_APPKEY"
$env:JUHE_FINANCE_NEWS_APPKEY="YOUR_JUHE_FINANCE_NEWS_APPKEY"
```
