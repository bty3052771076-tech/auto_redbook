"""Framework-independent local API contract. No secrets in returned objects."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from uuid import uuid4

from .presets import ADAPTERS, PRESETS
from .runtime import RuntimeClient
from .security import PlatformError, file_lock
from .store import atomic_json


def read_operation(path):
    record = json.loads(path.read_text(encoding='utf-8'))
    if record['status'] == 'running':
        try:
            with file_lock(path.with_suffix('.lease'), timeout=0):
                record = json.loads(path.read_text(encoding='utf-8'))
                if record['status'] == 'running':
                    record.update(status='failed', ended_at=time.time(), code='OPERATION_INTERRUPTED',
                                  error='检查进程已中断；没有自动重放，请重新发起检查')
                    atomic_json(path, record)
        except PlatformError as exc:
            if exc.code != 'CONFIG_BUSY':
                raise
    return record


def operation(store, action, identity, purpose, idempotency_key=''):
    fingerprint = hashlib.sha256(json.dumps([action, identity, purpose], sort_keys=True).encode()).hexdigest()
    key = hashlib.sha256((store.namespace + ':' + idempotency_key).encode()).hexdigest() if idempotency_key else uuid4().hex
    path = store.directory / 'operations' / (key + '.json')
    with file_lock(store.directory / 'operations.lock'):
        if path.exists():
            existing = read_operation(path)
            if existing['fingerprint'] != fingerprint:
                raise PlatformError('IDEMPOTENCY_CONFLICT', '同一操作编号不能用于不同模型', status=409)
            return existing
        record = {'operation_id': key, 'status': 'running', 'action': action, 'identity': identity,
                  'purpose': purpose, 'started_at': time.time(), 'fingerprint': fingerprint}
        lease = file_lock(path.with_suffix('.lease'), timeout=0)
        lease.__enter__()
        atomic_json(path, record)
    def run():
        try:
            client = RuntimeClient(store)
            if action == 'discover':
                record['result'] = store.discover(identity, client)
            elif action == 'connection':
                connection = store._find(store.state(), 'connections', identity)
                result = client.catalog(connection)
                record['result'] = {'reachable': True, 'authenticated': False, 'complete': result['complete']}
            else:
                record['result'] = store.check(identity, purpose, client)
            record['status'] = 'completed'
        except PlatformError as exc:
            record.update(status='failed', **exc.public())
        except Exception:
            record.update(status='failed', code='PLATFORM_CHECK_FAILED', error='模型检查未完成，请检查协议、网络和返回格式')
        record['ended_at'] = time.time()
        try:
            atomic_json(path, record)
        finally:
            lease.__exit__(None, None, None)
    threading.Thread(target=run, daemon=True, name='model-platform-check').start()
    return record.copy()


def platform_request(service, method, path, data=None, idempotency_key=''):
    store = service.model_platforms()
    data = dict(data or {})
    parts = path.removeprefix('/api/model-platforms/').strip('/').split('/')
    revision = data.pop('expected_revision', None)
    if method != 'GET' and parts[0] not in {'checks', 'resolve'} and not (len(parts) == 3 and parts[2] == 'discover'):
        if type(revision) is not int:
            raise PlatformError('REVISION_REQUIRED', '保存必须包含当前配置修订号，刷新后重试', status=409)
    if parts == ['presets'] and method == 'GET':
        return {'presets': PRESETS, 'adapters': sorted(ADAPTERS), 'revision': 2}
    if parts == ['connections']:
        if method == 'GET':
            state = store.catalog_rows()
            return {'connections': state['connections'], 'revision': state['revision']}
        if method == 'POST':
            if not idempotency_key:
                raise PlatformError('IDEMPOTENCY_REQUIRED', '新建连接需要操作编号')
            key = hashlib.sha256((store.namespace + ':' + idempotency_key).encode()).hexdigest()
            file = store.directory / 'mutations' / (key + '.json')
            digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            with file_lock(store.directory / 'mutations.lock'):
                if file.exists():
                    saved = json.loads(file.read_text(encoding='utf-8'))
                    if digest != saved['fingerprint']:
                        raise PlatformError('IDEMPOTENCY_CONFLICT', '操作编号已用于不同配置', status=409)
                    return store._find(store.state(), 'connections', saved['connection_id'])
                result = store.add_connection(data, revision)
                atomic_json(file, {'fingerprint': digest, 'connection_id': result['connection_id']})
                return result
    if len(parts) >= 2 and parts[0] == 'connections':
        identity = parts[1]
        if len(parts) == 2:
            if method == 'GET':
                return store._find(store.state(), 'connections', identity)
            if method == 'PATCH':
                return store.edit_connection(identity, data, revision)
            if method == 'DELETE':
                return store.remove_connection(identity, revision)
        if len(parts) == 3:
            if parts[2] == 'credential' and method in {'PUT', 'DELETE'}:
                return store.credential(identity, data, revision, clear=method == 'DELETE')
            if parts[2] == 'authorization' and method == 'PUT':
                return store.authorize(identity, data, revision)
            if parts[2] == 'discover' and method == 'POST':
                return operation(store, 'discover', identity, '', idempotency_key)
    if parts == ['models']:
        if method == 'GET':
            return store.catalog_rows()
        if method == 'POST':
            return store.add_model(data, revision)
    if len(parts) == 2 and parts[0] == 'models':
        if method == 'GET':
            return store._find(store.state(), 'models', parts[1])
        if method == 'PATCH':
            return store.edit_model(parts[1], data, revision)
    if parts == ['roles']:
        if method == 'GET':
            return {'roles': service.providers()['bindings'], 'revision': store.state()['revision']}
        if method == 'PUT':
            if revision != store.state()['revision']:
                raise PlatformError('REVISION_CONFLICT', '角色配置已变化，请刷新后保存', status=409)
            # Validate legacy identities at the compatibility boundary too.
            catalog = {r['id']: r for r in service.models()['rows']}
            for role, ref in data.items():
                if ref and not str(ref).startswith('m_'):
                    row = catalog.get(ref)
                    if not row or not row['selectable'] or row['kind'] != ('image' if role == 'image' else 'llm'):
                        raise PlatformError('MODEL_DISABLED', '原有模型不可执行，请重新选择')
            result = store.bind(data, revision, allow_legacy=True)
            return {'roles': {**service._provider_state()['bindings'], **result}, 'revision': store.state()['revision']}
    if parts == ['resolve'] and method == 'POST':
        return store.resolve(data.get('role', 'writer'), data.get('model_ref', ''))
    if parts == ['checks'] and method == 'POST':
        purpose = data.get('purpose', 'text')
        if purpose not in {'text', 'structured', 'tools', 'connection'}:
            raise PlatformError('CAPABILITY_UNSUPPORTED', '请选择文本、结构化、工具回环或连接检查')
        return operation(store, 'connection' if purpose == 'connection' else 'check',
                         data.get('connection_id', '') if purpose == 'connection' else data.get('model_ref', ''), purpose, idempotency_key)
    if len(parts) == 2 and parts[0] == 'operations' and method == 'GET':
        if not __import__('re').fullmatch(r'[a-f0-9]{32,64}', parts[1]):
            raise PlatformError('OPERATION_NOT_FOUND', '操作编号无效', status=404)
        file = store.directory / 'operations' / (parts[1] + '.json')
        if file.is_file():
            with file_lock(store.directory / 'operations.lock'):
                return read_operation(file)
    raise PlatformError('PLATFORM_ROUTE_NOT_FOUND', '模型平台接口不存在', status=404)
