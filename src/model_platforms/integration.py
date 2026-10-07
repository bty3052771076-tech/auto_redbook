from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from .runtime import RuntimeClient
from .store import PlatformError, PlatformStore


_ROLE_ENV = {'agent': 'CONTROLLER_MODEL_REF', 'writer': 'WRITER_MODEL_REF', 'image': 'IMAGE_MODEL_REF'}
_SNAPSHOT_FIELDS = {
    'schema_version', 'namespace', 'role', 'purpose', 'model_ref', 'model_revision', 'upstream_model_id',
    'model_name', 'connection_revision', 'connection_id', 'connection_name', 'adapter_version', 'adapter',
    'base_url', 'paths', 'network', 'auth_mode', 'credential_ref', 'credential_revision', 'authorization',
    'billing', 'parameters', 'concurrency', 'rate_limit_group', 'proxy_mode', 'fallbacks',
}


def checkpoint_models(env=None, *, saved=None):
    """Allowlisted public model metadata; authorization is not an API credential."""
    env = os.environ if env is None else env
    raw = saved.get('snapshots', {}) if saved else json.loads(env.get('RUN_MODEL_SNAPSHOTS') or '{}')
    if not isinstance(raw, dict):
        raise PlatformError('SNAPSHOT_INVALID', '运行模型快照必须是角色对象')
    if not raw and not saved and 'RUN_LEGACY_MODEL_ROLES' not in env:
        for role in ('agent', 'writer'):
            config = platform_config(role, env=env)
            if config:
                raw[role] = config.platform_snapshot
    snapshots = {}
    for role, value in raw.items():
        if role not in _ROLE_ENV or not isinstance(value, dict) or value.get('role') != role:
            raise PlatformError('SNAPSHOT_INVALID', '运行模型快照的角色不一致')
        snapshot = {key: value[key] for key in _SNAPSHOT_FIELDS if key in value}
        for key, fields in {
            'authorization': {'id', 'roles', 'max_requests', 'expires_at', 'credential_revision', 'risk_accepted', 'money_limit_verified'},
            'parameters': {'temperature', 'top_p', 'max_output_tokens', 'token_parameter', 'reasoning_effort'},
            'paths': {'generate', 'models'},
        }.items():
            snapshot[key] = {k: v for k, v in (snapshot.get(key) or {}).items() if k in fields}
        snapshots[role] = snapshot
    directory = (saved or {}).get('directory') or env.get('MODEL_PLATFORMS_DIR') or Path.cwd() / 'data/model_platforms'
    legacy = (saved or {}).get('legacy_roles') or json.loads(env.get('RUN_LEGACY_MODEL_ROLES') or '{}')
    configs = (saved or {}).get('legacy_configs') or json.loads(env.get('RUN_LEGACY_MODEL_CONFIGS') or '{}')
    return {'directory': str(Path(directory).resolve()), 'snapshots': snapshots,
            'namespace': (saved or {}).get('namespace') or env.get('MODEL_PLATFORMS_NAMESPACE', 'workflow'),
            'legacy_roles': {role: ref for role, ref in legacy.items() if role in _ROLE_ENV and isinstance(ref, str)},
            'legacy_configs': {role: {key: value for key, value in cfg.items() if key in {'provider', 'model', 'base_url', 'cost_class'}}
                               for role, cfg in configs.items() if role in _ROLE_ENV and isinstance(cfg, dict)}}


def resume_model_environment(checkpoint, env):
    saved = checkpoint.get('model_runtime')
    if not saved:
        directory = env.get('MODEL_PLATFORMS_DIR') or Path.cwd() / 'data/model_platforms'
        defaults = PlatformStore(directory, namespace=env.get('MODEL_PLATFORMS_NAMESPACE', 'workflow'), env=env).state()['roles']
        if any(str(env.get(name) or defaults.get(role) or '').startswith('m_') for role, name in _ROLE_ENV.items() if role != 'image'):
            raise PlatformError('SNAPSHOT_MISSING', '旧检查点没有自定义模型快照，请显式创建新计划；不自动换成当前默认模型')
        return {}
    runtime = checkpoint_models(env, saved=saved)
    result = {'MODEL_PLATFORMS_DIR': runtime['directory'], 'RUN_MODEL_SNAPSHOTS': json.dumps(runtime['snapshots'], ensure_ascii=False)}
    result['MODEL_PLATFORMS_NAMESPACE'] = runtime['namespace']
    result['RUN_LEGACY_MODEL_ROLES'] = json.dumps(runtime['legacy_roles'], ensure_ascii=False)
    result['RUN_LEGACY_MODEL_CONFIGS'] = json.dumps(runtime['legacy_configs'], ensure_ascii=False)
    for role, ref in runtime['legacy_roles'].items():
        if env.get(_ROLE_ENV[role]) and env[_ROLE_ENV[role]] != ref:
            raise PlatformError('SNAPSHOT_CONFLICT', '续跑模型与原快照冲突，请显式重配未完成项')
        result[_ROLE_ENV[role]] = ref
    for role, snapshot in runtime['snapshots'].items():
        if env.get(_ROLE_ENV[role]) and env[_ROLE_ENV[role]] != snapshot['model_ref']:
            raise PlatformError('SNAPSHOT_CONFLICT', '续跑模型与原快照冲突，请显式重配未完成项')
        result[_ROLE_ENV[role]] = snapshot['model_ref']
        result['MODEL_PLATFORMS_NAMESPACE'] = snapshot['namespace']
    return result


def frozen_legacy_config(role='writer', *, env=None):
    from dataclasses import replace
    env = os.environ if env is None else env
    ref = json.loads(env.get('RUN_LEGACY_MODEL_ROLES') or '{}').get(role)
    if not ref or role not in {'agent', 'writer'}:
        return None
    provider, separator, model = ref.partition(':')
    if not separator or not model:
        raise PlatformError('SNAPSHOT_INVALID', '旧模型快照标识损坏，请重新确认任务')
    config = legacy_controller(env, provider=provider, model=model, role=role)
    metadata = json.loads(env.get('RUN_LEGACY_MODEL_CONFIGS') or '{}').get(role) or {}
    if metadata and (metadata['model'] != model or metadata['provider'] != provider):
        raise PlatformError('SNAPSHOT_INVALID', '旧模型配置与冻结标识不一致')
    return replace(config, base_url=metadata.get('base_url') or config.base_url)


def freeze_run_environment(env, *, roles=('agent', 'writer')):
    runtime = checkpoint_models(env)
    legacy = dict(runtime['legacy_roles'])
    configs = dict(runtime['legacy_configs'])
    store = PlatformStore(runtime['directory'], namespace=runtime['namespace'], env=env)
    defaults = store.state()['roles']
    for role in roles:
        if role in runtime['snapshots']:
            continue
        ref = env.get(_ROLE_ENV[role]) or legacy.get(role) or defaults.get(role, '')
        if ref and ref.startswith('m_'):
            if 'RUN_LEGACY_MODEL_ROLES' in env:
                raise PlatformError('SNAPSHOT_CONFLICT', '本次冻结角色不能被新默认替换')
            runtime['snapshots'][role] = store.resolve(role, ref)
            continue
        if ref:
            provider, _, model = ref.partition(':')
        else:
            provider = env.get('AGENT_LLM_PROVIDER' if role == 'agent' else 'LLM_PROVIDER') or 'minimax'
            model = ''
        config = legacy_controller(env, provider=provider, model=model, role=role)
        legacy[role] = config.provider + ':' + config.model
        if role not in configs:
            from urllib.parse import urlsplit
            address = urlsplit(config.base_url)
            if address.username or address.password or address.query or address.fragment:
                raise PlatformError('UNSAFE_ADDRESS', '旧模型地址含认证信息，请改用安全基址和独立凭据')
            configs[role] = {'provider': config.provider, 'model': config.model, 'base_url': config.base_url, 'cost_class': config.cost_class}
    runtime.update(legacy_roles=legacy, legacy_configs=configs)
    return resume_model_environment({'model_runtime': runtime}, env)


def configuration(store: PlatformStore, snapshot: dict):
    from src.config import LLMConfig
    ref = snapshot.get('credential_ref', '')
    credentials = {ref[4:]: store.secrets.read(ref)} if ref.startswith('env:') else None
    return LLMConfig(model=snapshot['upstream_model_id'], api_key='', base_url=snapshot['base_url'],
                     provider=snapshot['connection_id'], cost_class='explicit_authorization',
                     account_scope=snapshot['rate_limit_group'], platform_snapshot=snapshot,
                     platform_directory=str(store.directory), platform_credentials=credentials)


def platform_config(role='writer', *, env=None, model_ref=None, purpose=None):
    env = os.environ if env is None else env
    directory = Path(env.get('MODEL_PLATFORMS_DIR') or Path.cwd() / 'data/model_platforms')
    store = PlatformStore(directory, namespace=env.get('MODEL_PLATFORMS_NAMESPACE', 'workflow'), env=env)
    try:
        snapshots = json.loads(env.get('RUN_MODEL_SNAPSHOTS') or '{}')
    except (TypeError, ValueError):
        raise PlatformError('SNAPSHOT_INVALID', '运行模型快照损坏，请重新确认计划') from None
    snapshot = snapshots.get(role)
    ref = model_ref or env.get({'agent': 'CONTROLLER_MODEL_REF', 'writer': 'WRITER_MODEL_REF', 'image': 'IMAGE_MODEL_REF'}[role])
    if snapshot and not model_ref:
        if ref and ref != snapshot['model_ref']:
            raise PlatformError('SNAPSHOT_CONFLICT', '运行中的模型与覆盖不一致，请显式重配未完成项')
        return configuration(store, snapshot)
    if 'RUN_LEGACY_MODEL_ROLES' in env and not model_ref and not ref:
        return None
    ref = ref or store.state()['roles'].get(role)
    if ref and str(ref).startswith('m_'):
        return configuration(store, store.resolve(role, ref, purpose=purpose))
    return None


def invoke(config, messages, *, max_tokens=4096):
    normalized = []
    for message in messages:
        if isinstance(message, dict):
            normalized.append(message)
        else:
            role = {'human': 'user', 'ai': 'assistant'}.get(message.type, message.type)
            normalized.append({'role': role, 'content': message.content})
    snapshot = config.platform_snapshot
    store = PlatformStore(config.platform_directory, namespace=snapshot['namespace'], env=config.platform_credentials)
    result = RuntimeClient(store).call(snapshot, normalized, max_tokens=max_tokens)
    if result.tool_calls:
        raise PlatformError('UNEXPECTED_TOOL_CALL', '此步骤只接受最终文本，不执行模型建议的工具')
    return SimpleNamespace(content=result.text, usage_metadata=result.usage)


def legacy_controller(env, *, model='', provider='', role='agent'):
    from src.config import LLMConfig, DEFAULT_MINIMAX_LLM_MODEL, _parse_llm_key_file
    selected = json.loads(env.get('RUN_LEGACY_MODEL_ROLES') or '{}').get(role, '')
    if selected and not provider and not model:
        provider, _, model = selected.partition(':')
    provider = provider or env.get('AGENT_LLM_PROVIDER') or 'minimax'
    fields = {
        'minimax': (['MINIMAX_TOKEN_PLAN_API_KEY'], 'MINIMAX_BASE_URL', 'https://api.minimax.cn/v1', 'MINIMAX_LLM_MODEL'),
        'aliyun': (['ALIYUN_LLM_API_KEY', 'DASHSCOPE_API_KEY'], 'ALIYUN_LLM_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'ALIYUN_LLM_MODEL'),
        'volcengine': (['VOLCENGINE_API_KEY', 'ARK_API_KEY'], 'VOLCENGINE_LLM_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3', 'VOLCENGINE_LLM_MODEL'),
        'siliconflow': (['SILICONFLOW_API_KEY'], 'SILICONFLOW_LLM_BASE_URL', 'https://api.siliconflow.cn/v1', 'SILICONFLOW_LLM_MODEL'),
    }
    if provider not in fields:
        raise PlatformError('MODEL_NOT_CONFIGURED', '请使用 model_ref 选择已验证连接，不自动切换到其他供应商')
    keys, url_key, base, model_key = fields[provider]
    if provider == 'minimax' and (env.get('MINIMAX_BILLING_MODE', 'subscription_only') not in {'subscription_only', 'subscription'} or
            any(env.get(k, '0').lower() in {'1', 'true', 'yes', 'on'} for k in ('MINIMAX_ALLOW_PAYGO', 'MINIMAX_ALLOW_PAID_CREDITS'))):
        raise PlatformError('BILLING_NOT_AUTHORIZED', 'MiniMax 主控仍须使用既有订阅限制，禁止按量回退')
    file_cfg = _parse_llm_key_file(Path('docs/minimax_api-key.md')) if provider == 'minimax' else {}
    if provider == 'minimax' and file_cfg.get('billing_mode', 'subscription_only') not in {'subscription_only', 'subscription'}:
        raise PlatformError('BILLING_NOT_AUTHORIZED', '本地 MiniMax 配置不符合订阅限制，请关闭按量回退')
    key = next((env[k] for k in keys if env.get(k)), '') or file_cfg.get('api_key', '')
    if not key:
        raise PlatformError('CREDENTIAL_UNAVAILABLE', '主控凭据缺失，请在连接管理配置')
    base_url = env.get(url_key) or (env.get('MINIMAX_LLM_BASE_URL') if provider == 'minimax' else '') or file_cfg.get('base_url') or base
    return LLMConfig(model=model or (env.get('AGENT_LLM_MODEL') if role == 'agent' else '') or env.get(model_key) or file_cfg.get('model') or DEFAULT_MINIMAX_LLM_MODEL,
                     api_key=key, base_url=base_url,
                     provider=provider, cost_class='subscription_included' if provider == 'minimax' else 'free')
