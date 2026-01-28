# 阿里云百炼（DashScope / 通义万相）(example)
#
# 使用说明：
# 1) 复制本文件为 `docs/z-image_api-key.md`
# 2) 填入你自己的 `api_key`
# 3) 确保 `docs/z-image_api-key.md` 不会被提交到 Git（已在 `.gitignore` 中忽略）
#
# 控制台（用于创建/查看 API Key、查看模型与配额）：
# - https://bailian.console.aliyun.com/cn-beijing/?tab=api#/api/?type=model&url=3002354
#
# 备注：
# - 百炼控制台是前端 SPA 页面；模型的具体调用参数/示例通常在控制台“API”页或官方文档中展示。
# - 本项目当前把图片生成当作 “provider”，后续我们会新增 `IMAGE_PROVIDER=z-image`（或类似名称）来读取该配置并调用接口。
#
# 常用固定配置建议（用于更稳定输出）：
# - 输出格式：png（避免 webp 兼容问题）
# - 尺寸：1024x1536（3:4 竖图）
#
# DashScope API Base URL（常见默认值）
base_url="https://dashscope.aliyuncs.com"

# 你的 API Key（替换）
api_key="YOUR_DASHSCOPE_API_KEY"

# （可选）区域/端点提示：你当前在 cn-beijing 控制台下操作
region="cn-beijing"

