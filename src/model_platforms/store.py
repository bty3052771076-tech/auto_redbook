from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from .presets import ADAPTERS, ROLE_PURPOSES
from .security import CredentialStore, PlatformError, file_lock, relative_path, validate_address


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class PlatformStore:
    def __init__(self, directory: Path | str, *, namespace: str = 'workflow', env: dict | None = None):
        self.directory = Path(directory)
        if namespace not in {'workflow', 'agent'}:
            raise PlatformError('INVALID_NAMESPACE', '模型配置命名空间无效')
        self.namespace = namespace
        self.secrets = CredentialStore(self.directory / 'secrets', env)

    def state(self):
        path = self.directory / 'registry.json'
        if not path.exists():
            value = {'schema_version': 2, 'revision': 0, 'connections': [], 'models': [], 'namespaces': {}}
        else:
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
                if value['schema_version'] != 2:
                    raise ValueError()
            except (KeyError, ValueError, OSError):
                raise PlatformError('CONFIG_INVALID', '模型配置损坏，已停止；请恢复 registry.json 备份') from None
        value['roles'] = value['namespaces'].get(self.namespace, {})
        return value

    def _mutate(self, expected_revision, fn):
        with file_lock(self.directory / 'registry.lock'):
            state = self.state()
            if expected_revision != state['revision']:
                raise PlatformError('REVISION_CONFLICT', '配置已变化，请刷新后重新保存', status=409)
            result = fn(state)
            state.pop('roles', None)
            state['revision'] += 1
            atomic_json(self.directory / 'registry.json', state)
            return copy.deepcopy(result)

    @staticmethod
    def _find(state, table, identity):
        field = 'connection_id' if table == 'connections' else 'model_ref'
        found = next((row for row in state[table] if row[field] == identity), None)
        if found is None:
            raise PlatformError('MODEL_NOT_FOUND', '连接或模型已不存在，请重新选择', status=404)
        return found

    def add_connection(self, data: dict, expected_revision: int | None = None):
        allowed = {'name', 'adapter', 'base_url', 'network', 'auth_mode', 'credential_env', 'api_key', 'billing',
                   'vendor_preset', 'paths', 'concurrency', 'rate_limit_group', 'proxy_mode'}
        if set(data) - allowed:
            raise PlatformError('INVALID_CONNECTION', '连接包含未支持的字段')
        name = str(data.get('name', '')).strip()
        adapter = data.get('adapter', 'openai_chat')
        if not name or len(name) > 80 or adapter not in ADAPTERS:
            raise PlatformError('INVALID_CONNECTION', '请填写名称并选择已实现协议')
        network = data.get('network', 'public')
        base = validate_address(str(data.get('base_url', '')), network)
        auth = data.get('auth_mode', 'bearer')
        if auth not in {'bearer', 'x-api-key', 'none'} or auth == 'none' and network != 'local':
            raise PlatformError('INVALID_AUTH', '公网服务需要认证，本机服务可选择无认证')
        paths = data.get('paths') or {}
        if not isinstance(paths, dict) or set(paths) - {'generate', 'models'}:
            raise PlatformError('UNSAFE_ENDPOINT', '只允许生成与目录相对路径')
        paths = {key: relative_path(str(value)) for key, value in paths.items()}
        billing = data.get('billing', 'unknown')
        if billing not in {'free', 'subscription', 'payg', 'unknown'}:
            raise PlatformError('INVALID_BILLING', '计费声明无效')
        proxy_mode = data.get('proxy_mode', 'inherit')
        if proxy_mode not in {'inherit', 'direct'}:
            raise PlatformError('INVALID_PROXY', '请选择继承系统代理或直连')
        credential_ref = self._credential(data)
        try:
            credential_fingerprint = self.secrets.fingerprint(credential_ref)
        except PlatformError:
            credential_fingerprint = ''
        connection_id = 'c_' + uuid4().hex
        limit = int(data.get('concurrency', 2))
        if not 1 <= limit <= 5:
            raise PlatformError('INVALID_CONCURRENCY', '连接并发必须为1至5')
        group = str(data.get('rate_limit_group') or connection_id)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', group):
            raise PlatformError('INVALID_RATE_GROUP', '限流组格式无效')
        row = {'connection_id': connection_id, 'name': name, 'adapter': adapter, 'base_url': base,
               'network': network, 'auth_mode': auth, 'credential_ref': credential_ref, 'credential_revision': 1,
               'credential_fingerprint': credential_fingerprint,
               'revision': 1, 'enabled': True, 'billing': billing, 'vendor_preset': data.get('vendor_preset', 'custom'),
               'paths': paths, 'concurrency': limit, 'rate_limit_group': group, 'proxy_mode': proxy_mode,
               'authorization': None, 'catalog': {'status': 'not_checked', 'complete': False}}
        def add(state):
            state['connections'].append(row)
            return row
        return self._mutate(self.state()['revision'] if expected_revision is None else expected_revision, add)

    def _credential(self, data):
        env = data.get('credential_env', '')
        key = data.get('api_key', '')
        if key and env:
            raise PlatformError('INVALID_CREDENTIAL', 'Key 和环境变量引用只能配置一项')
        if env:
            if not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', env):
                raise PlatformError('INVALID_CREDENTIAL', '环境变量名称无效')
            return 'env:' + env
        if key:
            if not isinstance(key, str) or len(key) > 8192 or '\n' in key or '\r' in key:
                raise PlatformError('INVALID_CREDENTIAL', '凭据格式无效')
            return self.secrets.save(key)
        return ''

    def edit_connection(self, identity, data, revision):
        if set(data) - {'name', 'enabled', 'base_url', 'adapter', 'paths', 'proxy_mode', 'concurrency'}:
            raise PlatformError('INVALID_CONNECTION', '修改字段无效，凭据请通过独立命令替换')
        def update(state):
            row = self._find(state, 'connections', identity)
            if 'name' in data and (not isinstance(data['name'], str) or not data['name'].strip() or len(data['name']) > 80):
                raise PlatformError('INVALID_CONNECTION', '名称不能为空或超过80字')
            # A different authentication target must be separately created and authorized.
            if any(key in data and data[key] != row[key] for key in ('base_url', 'adapter', 'paths')):
                raise PlatformError('AUTH_TARGET_CHANGED', '地址或协议改变请新建连接并重新授权，不自动转发旧凭据')
            if 'enabled' in data and not isinstance(data['enabled'], bool):
                raise PlatformError('INVALID_CONNECTION', '启用状态必须为布尔值')
            if 'concurrency' in data and (type(data['concurrency']) is not int or not 1 <= data['concurrency'] <= 5):
                raise PlatformError('INVALID_CONCURRENCY', '并发必须为1至5')
            if 'proxy_mode' in data and data['proxy_mode'] not in {'inherit', 'direct'}:
                raise PlatformError('INVALID_PROXY', '代理模式无效')
            row.update(data)
            row['revision'] += 1
            return row
        return self._mutate(revision, update)

    def credential(self, identity, data, revision, *, clear=False):
        ref = '' if clear else self._credential(data)
        if not clear and not ref:
            raise PlatformError('INVALID_CREDENTIAL', '替换凭据不能为空；请用清除命令')
        def update(state):
            row = self._find(state, 'connections', identity)
            row['credential_ref'] = ref
            row['credential_fingerprint'] = self.secrets.fingerprint(ref)
            row['credential_revision'] += 1
            row['revision'] += 1
            row['authorization'] = None
            return row
        return self._mutate(revision, update)

    def verify_credential(self, connection):
        if connection['auth_mode'] != 'none' and self.secrets.fingerprint(connection['credential_ref']) != connection.get('credential_fingerprint'):
            raise PlatformError('CREDENTIAL_CHANGED', '凭据值已变化，请在连接管理替换凭据后重新授权和测试；不复用旧账户授权')

    def add_model(self, data, revision):
        if set(data) - {'connection_id', 'upstream_model_id', 'name', 'enabled', 'parameters', 'origin'}:
            raise PlatformError('INVALID_MODEL', '模型字段无效')
        identity = data.get('upstream_model_id')
        if not isinstance(identity, str) or not identity or len(identity) > 512 or any(ord(c) < 33 for c in identity):
            raise PlatformError('INVALID_MODEL', '请输入原生模型 ID，不能包含空白或控制字符')
        params = self._parameters(data.get('parameters') or {})
        def add(state):
            self._find(state, 'connections', data['connection_id'])
            if any(row['connection_id'] == data['connection_id'] and row['upstream_model_id'] == identity for row in state['models']):
                raise PlatformError('MODEL_EXISTS', '该连接已存在此模型，请编辑现有条目', status=409)
            row = {'model_ref': 'm_' + uuid4().hex, 'connection_id': data['connection_id'], 'upstream_model_id': identity,
                   'name': str(data.get('name') or identity)[:120], 'enabled': data.get('enabled') is True,
                   'origin': data.get('origin', 'manual'), 'revision': 1, 'parameters': params,
                   'capabilities': {}, 'catalog_missing': False, 'favorite': False}
            state['models'].append(row)
            return row
        return self._mutate(revision, add)

    @staticmethod
    def _parameters(params):
        if not isinstance(params, dict) or set(params) - {'temperature', 'top_p', 'max_output_tokens', 'token_parameter', 'reasoning_effort'}:
            raise PlatformError('UNSUPPORTED_PARAMETER', '参数不受支持')
        if params.get('token_parameter', 'max_tokens') not in {'max_tokens', 'max_completion_tokens'}:
            raise PlatformError('UNSUPPORTED_PARAMETER', 'token 参数无效')
        if 'max_output_tokens' in params and (type(params['max_output_tokens']) is not int or not 256 <= params['max_output_tokens'] <= 64000):
            raise PlatformError('UNSUPPORTED_PARAMETER', '输出上限必须为256至64000')
        for key, upper in (('temperature', 2), ('top_p', 1)):
            if key in params and (type(params[key]) not in {int, float} or not 0 <= params[key] <= upper):
                raise PlatformError('UNSUPPORTED_PARAMETER', '采样参数必须在所选范围内')
        if 'reasoning_effort' in params and params['reasoning_effort'] not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
            raise PlatformError('UNSUPPORTED_PARAMETER', '推理强度无效')
        return params

    def edit_model(self, identity, data, revision):
        if set(data) - {'enabled', 'favorite', 'name', 'parameters'}:
            raise PlatformError('INVALID_MODEL', '只支持修改启用、收藏、展示名和参数')
        def update(state):
            row = self._find(state, 'models', identity)
            if any(key in data and type(data[key]) is not bool for key in ('enabled', 'favorite')):
                raise PlatformError('INVALID_MODEL', '启用和收藏必须为布尔值')
            if 'parameters' in data:
                data['parameters'] = self._parameters(data['parameters'])
                row['capabilities'] = {}
            if 'name' in data and (not isinstance(data['name'], str) or not data['name'].strip() or len(data['name']) > 120):
                raise PlatformError('INVALID_MODEL', '展示名无效')
            row.update(data)
            row['revision'] += 1
            return row
        return self._mutate(revision, update)

    def authorize(self, identity, data, revision):
        if data.get('risk_accepted') is not True:
            raise PlatformError('BILLING_NOT_AUTHORIZED', '请明确确认此连接可能产生费用；计费声明不是免费证据')
        roles = data.get('roles')
        count, expires = data.get('max_requests'), data.get('expires_at')
        if (not isinstance(roles, list) or not roles or set(roles) - {'agent', 'writer', 'vision_review'} or
                type(count) is not int or not 1 <= count <= 10000 or type(expires) not in {int, float} or
                not time.time() < expires <= time.time() + 31 * 86400):
            raise PlatformError('INVALID_AUTHORIZATION', '请指定角色、1至10000次请求及31天内到期时间')
        def update(state):
            row = self._find(state, 'connections', identity)
            row['authorization'] = {'id': uuid4().hex, 'roles': roles, 'max_requests': count,
                                    'expires_at': expires, 'credential_revision': row['credential_revision'],
                                    'risk_accepted': True, 'money_limit_verified': False}
            row['revision'] += 1
            return row
        return self._mutate(revision, update)

    def resolve(self, role, model_ref='', *, require_verified=True, purpose=None):
        state = self.state()
        if role not in ROLE_PURPOSES:
            raise PlatformError('INVALID_ROLE', '模型角色无效')
        model = self._find(state, 'models', model_ref or state['roles'].get(role, ''))
        connection = self._find(state, 'connections', model['connection_id'])
        purpose = purpose or ROLE_PURPOSES[role]
        if not connection['enabled'] or not model['enabled'] or model.get('catalog_missing'):
            raise PlatformError('MODEL_DISABLED', '请启用模型或重新确认已下架模型')
        if purpose not in {'text', 'structured', 'tools', 'vision'}:
            raise PlatformError('CAPABILITY_UNSUPPORTED', '此连接不支持该操作，请使用已有生图供应商')
        self.verify_credential(connection)
        evidence = model['capabilities'].get(purpose)
        if require_verified and (not evidence or evidence['credential_revision'] != connection['credential_revision'] or
                                 evidence['tested_at'] < time.time() - 86400):
            raise PlatformError('CAPABILITY_UNVERIFIED', '请在模型目录中测试对应能力，验证有效期24小时（不要求同步额度）')
        self._billing(connection, role)
        return {'schema_version': 2, 'namespace': self.namespace, 'role': role, 'purpose': purpose,
                'model_ref': model['model_ref'], 'model_revision': model['revision'], 'upstream_model_id': model['upstream_model_id'],
                'model_name': model['name'], 'connection_revision': connection['revision'], 'connection_id': connection['connection_id'],
                'connection_name': connection['name'], 'adapter_version': 1, 'adapter': connection['adapter'],
                'base_url': connection['base_url'], 'paths': connection['paths'], 'network': connection['network'],
                'auth_mode': connection['auth_mode'], 'credential_ref': connection['credential_ref'],
                'credential_revision': connection['credential_revision'], 'authorization': connection['authorization'],
                'billing': connection['billing'], 'parameters': model['parameters'], 'concurrency': connection['concurrency'],
                'rate_limit_group': connection['rate_limit_group'], 'proxy_mode': connection['proxy_mode'], 'fallbacks': []}

    @staticmethod
    def _billing(connection, role):
        auth = connection.get('authorization') or {}
        if role not in auth.get('roles', []) or auth.get('expires_at', 0) <= time.time() or auth.get('credential_revision') != connection['credential_revision']:
            raise PlatformError('BILLING_NOT_AUTHORIZED', '请为此连接及角色明确授权费用风险与请求次数，不自动使用按量或未知费用')

    def bind(self, data, revision, *, allow_legacy=False):
        if set(data) - set(ROLE_PURPOSES):
            raise PlatformError('INVALID_ROLE', '模型角色无效')
        for role, ref in data.items():
            if ref and str(ref).startswith('m_'):
                self.resolve(role, ref)
            elif ref and not allow_legacy:
                raise PlatformError('INVALID_MODEL', '旧模型必须通过已校验的兼容接口绑定')
        def update(state):
            roles = state['namespaces'].setdefault(self.namespace, {})
            roles.update(data)
            return dict(roles)
        return self._mutate(revision, update)

    def remove_connection(self, identity, revision):
        def remove(state):
            self._find(state, 'connections', identity)
            refs = {row['model_ref'] for row in state['models'] if row['connection_id'] == identity}
            if any(ref in refs for roles in state['namespaces'].values() for ref in roles.values()):
                raise PlatformError('CONNECTION_IN_USE', '先取消该连接的默认绑定，再停用连接；保留凭据与历史快照')
            row = self._find(state, 'connections', identity)
            row['enabled'] = False
            row['revision'] += 1
            return {'status': 'disabled', 'connection_id': identity}
        return self._mutate(revision, remove)

    def consume(self, snapshot):
        state = self.state()
        connection = self._find(state, 'connections', snapshot['connection_id'])
        model = self._find(state, 'models', snapshot['model_ref'])
        if not connection['enabled'] or not model['enabled']:
            raise PlatformError('MODEL_DISABLED', '连接或模型已停用，原任务等待处理，不切换模型')
        if connection['credential_revision'] != snapshot['credential_revision']:
            raise PlatformError('CREDENTIAL_CHANGED', '凭据已更换，原任务需要明确重配，不重新生成已完成内容')
        self.verify_credential(connection)
        if any(snapshot.get(key) != connection.get(key) for key in
               ('base_url', 'adapter', 'paths', 'network', 'auth_mode', 'credential_ref', 'rate_limit_group')) or model['upstream_model_id'] != snapshot['upstream_model_id']:
            raise PlatformError('SNAPSHOT_INVALID', '运行快照的认证目标或模型身份不匹配，已阻止发送凭据')
        self._billing(connection, snapshot['role'])
        if (connection['authorization'] or {}).get('id') != (snapshot.get('authorization') or {}).get('id'):
            raise PlatformError('AUTHORIZATION_CHANGED', '费用授权已变化，请重新确认任务')
        if snapshot.get('authorization') != connection.get('authorization'):
            raise PlatformError('SNAPSHOT_INVALID', '运行快照的费用授权与登记记录不匹配')
        auth = snapshot['authorization']
        path = self.directory / 'usage.json'
        with file_lock(self.directory / 'usage.lock'):
            value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            used = value.get(auth['id'], 0)
            if used >= auth['max_requests']:
                raise PlatformError('REQUEST_BUDGET_EXHAUSTED', '本地授权请求次数用完，请补充授权；这不是平台额度同步')
            value[auth['id']] = used + 1
            atomic_json(path, value)

    def check(self, ref, purpose, client):
        role = 'agent' if purpose in {'structured', 'tools'} else 'vision_review' if purpose == 'vision' else 'writer'
        snapshot = self.resolve(role, ref, require_verified=False, purpose=purpose)
        if purpose == 'vision':
            raise PlatformError('CAPABILITY_UNSUPPORTED', '本版本不开放自定义视觉审核，请保留已有视觉审核配置')
        messages = [{'role': 'user', 'content': 'Return only {"ok":true}' if purpose == 'structured' else 'Reply OK'}]
        if purpose == 'tools':
            messages = [{'role': 'user', 'content': 'Call echo with value ping, then report the returned value'}]
            result = client.call(snapshot, messages, tools=[{
                'name': 'echo', 'description': 'A harmless local echo test',
                'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'], 'additionalProperties': False}}])
            if len(result.tool_calls) != 1 or result.tool_calls[0]['name'] != 'echo' or result.tool_calls[0]['arguments'] != {'value': 'ping'}:
                raise PlatformError('TOOL_OUTPUT_INVALID', '模型未返回合法工具参数；未执行任何工具')
            messages += [{'role': 'assistant', 'content': '', 'tool_calls': result.tool_calls},
                         {'role': 'tool', 'tool_call_id': result.tool_calls[0]['id'], 'content': 'ping'}]
        result = client.call(snapshot, messages)
        if purpose == 'structured':
            try:
                valid = json.loads(result.text) == {'ok': True}
            except ValueError:
                valid = False
            if not valid:
                raise PlatformError('STRUCTURED_OUTPUT_INVALID', '模型未返回要求的完整 JSON')
        if purpose == 'tools' and 'ping' not in result.text.lower():
            raise PlatformError('TOOL_OUTPUT_INVALID', '工具结果回环验证失败')
        revision = self.state()['revision']
        def update(state):
            row = self._find(state, 'models', ref)
            connection = self._find(state, 'connections', snapshot['connection_id'])
            if connection['credential_revision'] != snapshot['credential_revision']:
                raise PlatformError('REVISION_CONFLICT', '验证期间凭据变化，请重新测试', status=409)
            if row['revision'] != snapshot['model_revision']:
                raise PlatformError('REVISION_CONFLICT', '验证期间模型配置变化，请重新测试', status=409)
            evidence = {'tested_at': time.time(), 'credential_revision': snapshot['credential_revision'], 'source': 'actual_call', 'scope': purpose}
            row['capabilities'][purpose] = evidence
            if purpose in {'structured', 'tools'}:
                row['capabilities']['text'] = dict(evidence, scope='text')
            row['revision'] += 1
            return {'status': 'verified', 'model_ref': ref, 'purpose': purpose, 'elapsed_s': result.elapsed_s}
        return self._mutate(revision, update)

    def discover(self, identity, client):
        state = self.state()
        revision = state['revision']
        connection = self._find(state, 'connections', identity)
        result = client.catalog(connection)
        def update(state):
            row = self._find(state, 'connections', identity)
            existing = {m['upstream_model_id']: m for m in state['models'] if m['connection_id'] == identity}
            for model_id in result['ids']:
                if model_id in existing:
                    existing[model_id]['catalog_missing'] = False
                else:
                    state['models'].append({'model_ref': 'm_' + uuid4().hex, 'connection_id': identity,
                        'upstream_model_id': model_id, 'name': model_id, 'enabled': False, 'origin': 'live',
                        'revision': 1, 'parameters': {}, 'capabilities': {}, 'catalog_missing': False, 'favorite': False})
            if result['complete'] and result['ids']:
                for model_id, model in existing.items():
                    if model['origin'] == 'live':
                        model['catalog_missing'] = model_id not in result['ids']
            row['catalog'] = {'status': 'success' if result['complete'] and result['ids'] else 'partial', 'complete': result['complete'],
                              'count': len(result['ids']), 'at': time.time(), 'authenticated': False}
            return row['catalog']
        return self._mutate(revision, update)

    def catalog_rows(self):
        state = self.state()
        connections = {c['connection_id']: c for c in state['connections']}
        rows = []
        for model in state['models']:
            conn = connections[model['connection_id']]
            reasons = {}
            for role in ('agent', 'writer'):
                try:
                    self.resolve(role, model['model_ref'])
                    reasons[role] = ''
                except PlatformError as exc:
                    reasons[role] = str(exc)
            rows.append(dict(model, connection_name=conn['name'], billing=conn['billing'], eligible=reasons))
        return {'revision': state['revision'], 'connections': state['connections'], 'models': rows, 'roles': state['roles'], 'namespace': self.namespace}
