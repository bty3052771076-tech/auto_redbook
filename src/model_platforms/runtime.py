from __future__ import annotations

import hashlib
import json
import ssl
import time
from urllib.request import getproxies, proxy_bypass
from contextlib import ExitStack
from dataclasses import dataclass

import httpx

from .security import PlatformError, file_lock, pinned_address, relative_path


@dataclass(frozen=True)
class ModelResult:
    text: str
    tool_calls: list[dict]
    usage: dict
    finish_reason: str
    request_id: str
    elapsed_s: float


def tool_call(identity, name, arguments):
    try:
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(arguments, dict) or not identity or not name:
            raise ValueError()
        return {'id': identity, 'name': name, 'arguments': arguments}
    except (ValueError, TypeError):
        raise PlatformError('TOOL_OUTPUT_INVALID', '工具参数不是合法 JSON 对象；未执行工具') from None


def encode(snapshot, messages, max_tokens, tools=None):
    adapter = snapshot['adapter']
    params = snapshot.get('parameters') or {}
    maximum = min(int(params.get('max_output_tokens', max_tokens)), int(max_tokens))
    body = {'model': snapshot['upstream_model_id']}
    for key in ('temperature', 'top_p', 'reasoning_effort'):
        if key in params and not (adapter == 'anthropic_messages' and key == 'reasoning_effort'):
            body[key] = params[key]
    if adapter == 'openai_chat':
        body.update(messages=[dict(m) for m in messages], stream=False)
        body[params.get('token_parameter', 'max_tokens')] = maximum
        for message in body['messages']:
            if message.get('tool_calls'):
                message['tool_calls'] = [{'id': t['id'], 'type': 'function', 'function': {
                    'name': t['name'], 'arguments': json.dumps(t['arguments'])}} for t in message['tool_calls']]
        if tools:
            body['tools'] = [{'type': 'function', 'function': t} for t in tools]
        path = 'chat/completions'
    elif adapter == 'openai_responses':
        inputs = []
        for message in messages:
            if message['role'] == 'tool':
                inputs.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': message['content']})
            else:
                if message.get('content'):
                    inputs.append({'role': message['role'], 'content': message['content']})
                inputs.extend({'type': 'function_call', 'call_id': t['id'], 'name': t['name'],
                               'arguments': json.dumps(t['arguments'])} for t in message.get('tool_calls', []))
        body.update(input=inputs, max_output_tokens=maximum, stream=False, store=False)
        if 'reasoning_effort' in body:
            body['reasoning'] = {'effort': body.pop('reasoning_effort')}
        if tools:
            body['tools'] = [{'type': 'function', **t} for t in tools]
        path = 'responses'
    elif adapter == 'anthropic_messages':
        body.update(max_tokens=maximum, system='\n'.join(m['content'] for m in messages if m['role'] == 'system'))
        output = []
        for message in messages:
            if message['role'] == 'system':
                continue
            if message['role'] == 'tool':
                output.append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': message['tool_call_id'], 'content': message['content']}]})
            else:
                content = [{'type': 'text', 'text': message['content']}] if message.get('content') else []
                content.extend({'type': 'tool_use', 'id': t['id'], 'name': t['name'], 'input': t['arguments']} for t in message.get('tool_calls', []))
                output.append({'role': message['role'], 'content': content})
        body['messages'] = output
        if tools:
            body['tools'] = [{'name': t['name'], 'description': t.get('description', ''), 'input_schema': t['parameters']} for t in tools]
        path = 'messages'
    else:
        raise PlatformError('ADAPTER_UNSUPPORTED', '协议未实现，请选择已实现协议')
    return snapshot.get('paths', {}).get('generate', path), body


def decode(adapter, data, elapsed):
    calls, text = [], ''
    try:
        if adapter == 'openai_chat':
            choice = data['choices'][0]
            reason = choice['finish_reason']
            message = choice['message']
            if message.get('refusal'):
                raise PlatformError('OUTPUT_REFUSED', '模型拒绝此次请求，请修改输入')
            content = message.get('content') or ''
            text = content if isinstance(content, str) else ''.join(p.get('text', '') for p in content if p.get('type') == 'text')
            calls = [tool_call(t['id'], t['function']['name'], t['function']['arguments']) for t in message.get('tool_calls', [])]
            valid = {'stop', 'tool_calls'}
        elif adapter == 'openai_responses':
            reason = data['status']
            for item in data.get('output', []):
                if item.get('type') == 'message':
                    for part in item.get('content', []):
                        if part.get('type') == 'refusal':
                            raise PlatformError('OUTPUT_REFUSED', '模型拒绝此次请求，请修改输入')
                        if part.get('type') == 'output_text':
                            text += part['text']
                if item.get('type') == 'function_call':
                    calls.append(tool_call(item['call_id'], item['name'], item['arguments']))
            valid = {'completed'}
        else:
            reason = data['stop_reason']
            text = ''.join(p['text'] for p in data.get('content', []) if p.get('type') == 'text')
            calls = [tool_call(p['id'], p['name'], p['input']) for p in data.get('content', []) if p.get('type') == 'tool_use']
            valid = {'end_turn', 'tool_use'}
        if reason not in valid:
            raise PlatformError('OUTPUT_INCOMPLETE', '输出被截断、拒绝或未完成；未当作成功内容，未自动重放')
        if not text.strip() and not calls:
            raise PlatformError('OUTPUT_EMPTY', '模型未返回最终正文或工具请求，思考内容不计入正文')
        return ModelResult(text, calls, data.get('usage') or {}, reason, str(data.get('id') or ''), elapsed)
    except (KeyError, IndexError, TypeError, AttributeError):
        raise PlatformError('OUTPUT_INVALID', '模型响应不符合所选协议，请检查协议和模型') from None


class OriginTLSContext(ssl.SSLContext):
    """Keep API certificate/SNI validation when a proxy CONNECT targets a pinned IP."""
    def __new__(cls, hostname):
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, hostname):
        self.origin_hostname = hostname
        self.load_default_certs()

    def wrap_socket(self, *args, **kwargs):
        kwargs['server_hostname'] = self.origin_hostname
        return super().wrap_socket(*args, **kwargs)

    def wrap_bio(self, *args, **kwargs):
        kwargs['server_hostname'] = self.origin_hostname
        return super().wrap_bio(*args, **kwargs)


class RuntimeClient:
    def __init__(self, store, *, transport=None):
        self.store, self.transport = store, transport

    def _request(self, connection, path, method='POST', body=None, query=None, *, timeout=60, byte_budget=None):
        base = connection['base_url']
        path = relative_path(path)
        secret = '' if connection['auth_mode'] == 'none' else self.store.secrets.read(connection['credential_ref'])
        headers = {'Accept': 'application/json'}
        if secret:
            headers['x-api-key' if connection['auth_mode'] == 'x-api-key' else 'Authorization'] = secret if connection['auth_mode'] == 'x-api-key' else 'Bearer ' + secret
        if connection['adapter'] == 'anthropic_messages':
            headers['anthropic-version'] = '2023-06-01'
        url = httpx.URL(base + '/' + path)
        tls = OriginTLSContext(url.host)
        extensions = {}
        proxy = None
        if connection['network'] != 'local' and connection.get('proxy_mode') != 'direct' and not proxy_bypass(url.host):
            proxies = getproxies()
            proxy = proxies.get(url.scheme) or proxies.get('all')
        # Proxies receive the checked IP too; TLS/Host retain the original API hostname.
        if self.transport is None:
            address = pinned_address(base, connection['network'])
            headers['Host'] = url.netloc.decode()
            extensions['sni_hostname'] = url.host
            url = url.copy_with(host=address)
        started = time.monotonic()
        byte_budget = byte_budget if byte_budget is not None else {'remaining': 4 * 1024 * 1024}
        try:
            with httpx.Client(timeout=httpx.Timeout(max(.01, timeout), connect=min(10, timeout)), follow_redirects=False,
                              trust_env=False, verify=tls, proxy=proxy if self.transport is None else None, transport=self.transport) as client:
                with client.stream(method, url, headers=headers, json=body, params=query, extensions=extensions) as response:
                    if response.status_code != 200:
                        code = 'CREDENTIAL_REJECTED' if response.status_code in {401, 403} else 'RATE_LIMITED' if response.status_code == 429 else 'UPSTREAM_HTTP_ERROR'
                        raise PlatformError(code, f'上游 HTTP {response.status_code}；请检查凭据、套餐、模型或网络，不自动切换其他平台', retryable=response.status_code in {429, 502, 503, 504})
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started > timeout:
                            raise PlatformError('MODEL_TIMEOUT', '接口超过单次总超时，已停止读取', retryable=True)
                        content.extend(chunk)
                        byte_budget['remaining'] -= len(chunk)
                        if byte_budget['remaining'] < 0:
                            raise PlatformError('RESPONSE_TOO_LARGE', '响应超过4MiB，已中止')
                    return json.loads(content)
        except httpx.TimeoutException:
            raise PlatformError('MODEL_TIMEOUT', '接口超过单次超时，请检查服务或稍后重试', retryable=True) from None
        except httpx.RequestError:
            raise PlatformError('CONNECTION_FAILED', '网络请求失败，请检查地址、代理与服务', retryable=True) from None
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError('OUTPUT_INVALID', '接口没有返回合法 JSON') from None

    def call(self, snapshot, messages, *, max_tokens=4096, tools=None):
        path, body = encode(snapshot, messages, max_tokens, tools)
        group = hashlib.sha256(snapshot['rate_limit_group'].encode()).hexdigest()
        limits = [c['concurrency'] for c in self.store.state()['connections']
                  if c['enabled'] and c['rate_limit_group'] == snapshot['rate_limit_group']]
        concurrency = min([snapshot['concurrency'], *limits])
        # All applications sharing this directory share these bounded OS leases.
        deadline = time.monotonic() + 60
        while True:
            stack = ExitStack()
            for index in range(concurrency):
                try:
                    stack.enter_context(file_lock(self.store.directory / 'leases' / f'{group}-{index}.lock', timeout=0))
                    break
                except PlatformError:
                    continue
            else:
                stack.close()
                if time.monotonic() >= deadline:
                    raise PlatformError('MODEL_QUEUE_TIMEOUT', '连接并发队列等待超时，请稍后重试', retryable=True)
                time.sleep(.05)
                continue
            with stack:
                self.store.consume(snapshot)
                start = time.monotonic()
                data = self._request(snapshot, path, body=body)
                return decode(snapshot['adapter'], data, time.monotonic() - start)

    def catalog(self, connection):
        start = time.monotonic()
        budget = {'remaining': 4 * 1024 * 1024}
        ids, next_id = [], None
        for page in range(20):
            if time.monotonic() - start >= 30:
                return {'ids': ids, 'complete': False}
            try:
                data = self._request(connection, connection.get('paths', {}).get('models', 'models'), method='GET',
                                     query={'after_id': next_id} if next_id else None,
                                     timeout=max(.01, 30 - (time.monotonic() - start)), byte_budget=budget)
            except PlatformError as exc:
                if ids and exc.code in {'MODEL_TIMEOUT', 'RESPONSE_TOO_LARGE'}:
                    return {'ids': ids, 'complete': False}
                raise
            entries = data.get('data')
            if not isinstance(entries, list):
                raise PlatformError('CATALOG_INVALID', '目录不符合此协议，可手动添加模型')
            for row in entries:
                identity = row.get('id') if isinstance(row, dict) else None
                if isinstance(identity, str) and identity and len(identity) <= 512 and not any(ord(c) < 33 for c in identity) and identity not in ids:
                    ids.append(identity)
                if len(ids) >= 2000:
                    return {'ids': ids, 'complete': False}
            if data.get('has_more') is not True:
                return {'ids': ids, 'complete': bool(ids)}
            candidate = data.get('last_id')
            if not candidate or candidate == next_id:
                return {'ids': ids, 'complete': False}
            next_id = candidate
        return {'ids': ids, 'complete': False}
