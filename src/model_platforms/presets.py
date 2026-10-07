# Addresses are templates, never evidence of account billing or model capability.
PRESETS = [
    {'id': 'custom', 'name': '自定义 API', 'adapter': 'openai_chat', 'base_url': '', 'network': 'public', 'auth_mode': 'bearer'},
    {'id': 'openai', 'name': 'OpenAI API', 'adapter': 'openai_responses', 'base_url': 'https://api.openai.com/v1', 'network': 'public', 'auth_mode': 'bearer'},
    {'id': 'anthropic', 'name': 'Anthropic / Claude', 'adapter': 'anthropic_messages', 'base_url': 'https://api.anthropic.com/v1', 'network': 'public', 'auth_mode': 'x-api-key'},
    {'id': 'gemini', 'name': 'Gemini 兼容 API', 'adapter': 'openai_chat', 'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai', 'network': 'public', 'auth_mode': 'bearer'},
    {'id': 'deepseek', 'name': 'DeepSeek API', 'adapter': 'openai_chat', 'base_url': 'https://api.deepseek.com', 'network': 'public', 'auth_mode': 'bearer'},
    {'id': 'minimax', 'name': 'MiniMax（自定义端点）', 'adapter': 'openai_chat', 'base_url': 'https://api.minimax.cn/v1', 'network': 'public', 'auth_mode': 'bearer'},
    {'id': 'ollama', 'name': 'Ollama / 本机服务', 'adapter': 'openai_chat', 'base_url': 'http://127.0.0.1:11434/v1', 'network': 'local', 'auth_mode': 'none'},
    {'id': 'opencodex', 'name': 'opencodex 本机代理', 'adapter': 'openai_responses', 'base_url': 'http://127.0.0.1:8080/v1', 'network': 'local', 'auth_mode': 'bearer'},
]
ADAPTERS = {'openai_chat', 'openai_responses', 'anthropic_messages'}
ROLE_PURPOSES = {'agent': 'structured', 'writer': 'text', 'image': 'image', 'vision_review': 'vision'}
