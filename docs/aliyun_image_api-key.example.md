# 阿里云百炼 / DashScope 图像生成（example）
#
# 使用说明：
# 1) 复制本文件为 `docs/aliyun_image_api-key.md`
# 2) 填入你自己的 `api_key`
# 3) 确保 `docs/aliyun_image_api-key.md` 不会被提交到 Git（已在 `.gitignore` 中忽略）
#
# 百炼控制台（API 页面）：
# - https://bailian.console.aliyun.com/cn-beijing/?tab=api#/api/?type=model&url=3002354
#
# 说明：
# - 该 API Key 通常可用于多个模型；因此这里不固定 `model` 字段。
# - 具体模型名称/版本在“调用时”由代码或命令行参数指定。
# - 支持模型示例：qwen-image-max / qwen-image-plus / qwen-image / z-image-turbo / wan2.6-t2i / wanx2.1-t2i-turbo ...
#
# DashScope API Base URL（常见默认值）
base_url="https://dashscope.aliyuncs.com"

# 你的 API Key（替换）
api_key="YOUR_ALIYUN_BAILIAN_API_KEY"

# （可选）区域信息（你当前使用 cn-beijing 控制台）
region="cn-beijing"
