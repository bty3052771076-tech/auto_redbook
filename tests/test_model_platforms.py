import importlib.util
import json
import os
import time

import httpx
import pytest


def platform_module():
    assert importlib.util.find_spec('src.model_platforms') is not None, 'Unified model platform runtime is missing'
    from src.model_platforms import PlatformStore, PlatformError, RuntimeClient
    return PlatformStore, PlatformError, RuntimeClient


def configured(tmp_path, monkeypatch, adapter='openai_chat'):
    Store, _, _ = platform_module()
    monkeypatch.setenv('TEST_PLATFORM_KEY', 'synthetic-canary-platform-key')
    monkeypatch.setenv('MODEL_PLATFORMS_NAMESPACE', 'workflow')
    store = Store(tmp_path, namespace='workflow')
    conn = store.add_connection({'name': 'Test API', 'adapter': adapter, 'base_url': 'http://127.0.0.1:11434/v1',
                                 'network': 'local', 'auth_mode': 'bearer', 'credential_env': 'TEST_PLATFORM_KEY'})
    model = store.add_model({'connection_id': conn['connection_id'], 'upstream_model_id': 'org/model:preview',
                            'enabled': True}, store.state()['revision'])
    store.authorize(conn['connection_id'], {'roles': ['agent', 'writer'], 'risk_accepted': True,
                     'max_requests': 100, 'expires_at': time.time() + 3600}, store.state()['revision'])
    return store, conn, model


def test_unverified_model_cannot_be_used_or_claim_free(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, _ = platform_module()
    with pytest.raises(Error, match='CAPABILITY_UNVERIFIED'):
        store.resolve('writer', model['model_ref'])
    public = json.dumps(store.state())
    assert 'synthetic-canary-platform-key' not in public
    assert conn['billing'] == 'unknown'


@pytest.mark.parametrize('adapter, response, expected_path', [
    ('openai_chat', {'choices': [{'message': {'content': 'OK', 'reasoning_content': 'secret thought'}, 'finish_reason': 'stop'}]}, '/v1/chat/completions'),
    ('openai_responses', {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': []}, {'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}, '/v1/responses'),
    ('anthropic_messages', {'content': [{'type': 'thinking', 'thinking': 'secret thought'}, {'type': 'text', 'text': 'OK'}], 'stop_reason': 'end_turn'}, '/v1/messages'),
])
def test_protocols_preserve_model_id_and_return_only_final_text(tmp_path, monkeypatch, adapter, response, expected_path):
    store, conn, model = configured(tmp_path, monkeypatch, adapter)
    _, _, Client = platform_module()
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    client = Client(store, transport=httpx.MockTransport(respond))
    result = client.call(store.resolve('writer', model['model_ref'], require_verified=False),
                         [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'hello'}])
    assert result.text == 'OK'
    assert requests[0].url.path == expected_path
    assert json.loads(requests[0].content)['model'] == 'org/model:preview'
    assert 'secret thought' not in result.text
    if adapter == 'anthropic_messages':
        assert requests[0].headers['anthropic-version'] == '2023-06-01'
        assert json.loads(requests[0].content)['system'] == 'system'


def test_checks_bind_roles_and_stale_edits_do_not_overwrite(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    client = Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]})))
    store.check(model['model_ref'], 'structured', client)
    revision = store.state()['revision']
    store.bind({'agent': model['model_ref']}, revision)
    assert store.resolve('agent')['upstream_model_id'] == 'org/model:preview'
    with pytest.raises(Error, match='REVISION_CONFLICT'):
        store.bind({'writer': model['model_ref']}, revision)
    assert store.state()['roles']['agent'] == model['model_ref']


def test_truncated_and_refused_output_are_not_success(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    client = Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]})))
    with pytest.raises(Error, match='OUTPUT_INCOMPLETE'):
        client.call(store.resolve('writer', model['model_ref'], require_verified=False), [{'role': 'user', 'content': 'hi'}])


def test_catalog_partial_keeps_previous_models_and_binding(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, _, Client = platform_module()
    client = Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'data': [{'id': 'new/model'}], 'has_more': True})))
    result = store.discover(conn['connection_id'], client)
    assert result['complete'] is False
    assert any(m['model_ref'] == model['model_ref'] for m in store.state()['models'])
    assert not next(m for m in store.state()['models'] if m['upstream_model_id'] == 'new/model')['enabled']


@pytest.mark.parametrize('url,network', [
    ('http://example.com/v1', 'public'), ('https://user:pass@example.com/v1', 'public'),
    ('https://example.com/v1?key=secret', 'public'), ('http://169.254.169.254/v1', 'local'),
    ('https://127.0.0.1/v1', 'public'),
])
def test_unsafe_addresses_rejected_before_request(tmp_path, url, network):
    Store, Error, _ = platform_module()
    with pytest.raises(Error, match='UNSAFE'):
        Store(tmp_path).add_connection({'name': 'unsafe', 'adapter': 'openai_chat', 'base_url': url,
                                       'network': network, 'auth_mode': 'none'})


def test_explicit_writer_snapshot_overrides_legacy_provider_without_environment_mutation(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, _, Client = platform_module()
    client = Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]})))
    store.check(model['model_ref'], 'structured', client)
    monkeypatch.setenv('MODEL_PLATFORMS_DIR', str(tmp_path))
    monkeypatch.setenv('WRITER_MODEL_REF', model['model_ref'])
    monkeypatch.setenv('LLM_PROVIDER', 'ppinfra')
    from src.config import load_llm_configs
    before = dict(os.environ)
    config = load_llm_configs()[0]
    assert config.model == 'org/model:preview'
    assert config.api_key == ''
    assert config.platform_snapshot['adapter'] == 'openai_chat'
    assert dict(os.environ) == before


def test_workbench_projects_custom_models_and_freezes_selected_roles(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    assert hasattr(service, 'model_platforms'), 'Workbench has no unified model platform service'
    store, conn, model = configured(tmp_path / 'data/model_platforms', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    catalog = service.models()['rows']
    assert next(row for row in catalog if row['id'] == model['model_ref'])['selectable']
    service.save_model_bindings({'agent': model['model_ref'], 'writer': model['model_ref'], 'image': ''})
    assert service.providers()['bindings']['agent'] == model['model_ref']
    _, env = service.plan({'kind': 'agent', 'agent_id': model['model_ref'], 'llm_id': model['model_ref']}, 'a' * 32)
    snapshots = json.loads(env['RUN_MODEL_SNAPSHOTS'])
    assert snapshots['agent']['model_ref'] == model['model_ref']
    assert snapshots['writer']['model_ref'] == model['model_ref']
    assert 'synthetic-canary-platform-key' not in env['RUN_MODEL_SNAPSHOTS']


def test_controller_compaction_uses_agent_not_writer(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    monkeypatch.setenv('MODEL_PLATFORMS_DIR', str(tmp_path))
    monkeypatch.setenv('CONTROLLER_MODEL_REF', model['model_ref'])
    monkeypatch.setenv('WRITER_MODEL_REF', 'm_wrong_writer')
    captured = []
    from src.llm import generate
    from src.agent.compaction import minimax_summary
    monkeypatch.setattr(generate, 'generate_json', lambda config, **kwargs: captured.append(config) or {'summary': 'done', 'constraints': []})
    minimax_summary({'messages': []})
    assert captured[0].model == 'org/model:preview'


def test_custom_controller_is_accepted_only_with_resolvable_verified_snapshot(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    monkeypatch.setenv('MODEL_PLATFORMS_DIR', str(tmp_path))
    monkeypatch.setenv('CONTROLLER_MODEL_REF', model['model_ref'])
    from src.agent.editorial_agent import EditorialAgentConfig
    assert EditorialAgentConfig(provider='custom').validate().provider == 'custom'


def test_backend_platform_contract_requires_revision_and_never_returns_key(tmp_path, monkeypatch, workbench_factory):
    from src.model_platforms import service as module
    assert hasattr(module, 'platform_request'), 'Shared platform API is missing'
    service = workbench_factory(tmp_path)
    response = module.platform_request(service, 'POST', '/api/model-platforms/connections', {
        'name': 'Local test', 'base_url': 'http://127.0.0.1:11434/v1', 'adapter': 'openai_chat',
        'network': 'local', 'auth_mode': 'none', 'expected_revision': 0}, 'create-once')
    again = module.platform_request(service, 'POST', '/api/model-platforms/connections', {
        'name': 'Local test', 'base_url': 'http://127.0.0.1:11434/v1', 'adapter': 'openai_chat',
        'network': 'local', 'auth_mode': 'none', 'expected_revision': 0}, 'create-once')
    assert response['connection_id'] == again['connection_id']
    listing = module.platform_request(service, 'GET', '/api/model-platforms/connections', {}, '')
    assert len(listing['connections']) == 1
    assert listing['revision'] == 1
    _, Error, _ = platform_module()
    with pytest.raises(Error, match='REVISION_CONFLICT'):
        module.platform_request(service, 'PATCH', '/api/model-platforms/connections/' + response['connection_id'],
                                {'name': 'changed', 'expected_revision': 0}, '')


def test_parameter_edit_invalidates_old_capability_evidence(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.edit_model(model['model_ref'], {'parameters': {'max_output_tokens': 1024, 'token_parameter': 'max_completion_tokens'}}, store.state()['revision'])
    with pytest.raises(Error, match='CAPABILITY_UNVERIFIED'):
        store.resolve('agent', model['model_ref'])


def test_discovery_cannot_commit_a_stale_connection_result(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, _ = platform_module()
    class UpdatingCatalog:
        def catalog(self, connection):
            store.edit_connection(connection['connection_id'], {'enabled': False}, store.state()['revision'])
            return {'ids': ['stale'], 'complete': True}
    with pytest.raises(Error, match='REVISION_CONFLICT'):
        store.discover(conn['connection_id'], UpdatingCatalog())
    assert len(store.state()['models']) == 1


def test_gui_env_credential_can_invoke_without_mutating_process_env(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    monkeypatch.delenv('TEST_PLATFORM_KEY')
    store.secrets.env = {'TEST_PLATFORM_KEY': 'synthetic-local-config-key'}
    store.credential(conn['connection_id'], {'credential_env': 'TEST_PLATFORM_KEY'}, store.state()['revision'])
    store.authorize(conn['connection_id'], {'roles': ['writer'], 'risk_accepted': True, 'max_requests': 10,
        'expires_at': time.time() + 60}, store.state()['revision'])
    from src.model_platforms.integration import configuration, invoke
    snapshot = store.resolve('writer', model['model_ref'], require_verified=False)
    config = configuration(store, snapshot)
    captured = []
    from src.model_platforms.runtime import RuntimeClient
    original = RuntimeClient._request
    def request(self, connection, *args, **kwargs):
        captured.append(self.store.secrets.read(connection['credential_ref']))
        return {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr(RuntimeClient, '_request', request)
    assert invoke(config, [{'role': 'user', 'content': 'hello'}]).content == 'OK'
    assert captured == ['synthetic-local-config-key']
    assert 'TEST_PLATFORM_KEY' not in os.environ


def test_resume_freezes_old_snapshot_and_non_generation_needs_no_model(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    store, conn, model = configured(tmp_path / 'data/model_platforms', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.bind({'agent': model['model_ref'], 'writer': model['model_ref']}, store.state()['revision'])
    frozen = json.loads(service.freeze_model_roles({}, {})['RUN_MODEL_SNAPSHOTS'])
    service.jobs['a' * 32] = {'id': 'a' * 32, 'model_snapshots': frozen}
    store.bind({'agent': '', 'writer': ''}, store.state()['revision'])
    env = service.freeze_model_roles({}, {'resume_model_job_id': 'a' * 32})
    assert json.loads(env['RUN_MODEL_SNAPSHOTS']) == frozen
    store.edit_model(model['model_ref'], {'enabled': False}, store.state()['revision'])
    store._mutate(store.state()['revision'], lambda s: s['namespaces']['workflow'].update(agent=model['model_ref']))
    args, env = service.plan({'kind': 'login'}, 'b' * 32)
    assert 'RUN_MODEL_SNAPSHOTS' not in env


def test_custom_model_preflight_does_not_require_legacy_llm_quota(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path / 'models', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    monkeypatch.setenv('MODEL_PLATFORMS_DIR', str(store.directory))
    monkeypatch.setenv('WRITER_MODEL_REF', model['model_ref'])
    monkeypatch.setenv('LLM_PROVIDER', 'custom')
    from apps import cli
    monkeypatch.setattr(cli, '_refresh_metrics_for_preflight', lambda **kwargs: None)
    monkeypatch.setattr(cli, '_refresh_quotas_for_preflight', lambda **kwargs: pytest.fail('Custom models must not refresh legacy quotas'))
    result = cli._prepare_auto_pipeline(headless=True, login_hold=0, wait_timeout=5,
        metrics_max_age_hours=24, quota_max_age_hours=2, require_image=False,
        metrics_path=tmp_path / 'metrics.csv', quota_dir=tmp_path / 'quota', provider_keys={})
    assert result.quota_mode == 'connection_authorized'
    assert result.model_plan.llm.provider == conn['connection_id']
    assert result.model_plan.llm.cost_class == 'explicit_authorization'


@pytest.mark.parametrize('adapter', ['openai_chat', 'openai_responses', 'anthropic_messages'])
def test_harmless_tool_roundtrip_preserves_call_and_result(adapter, tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch, adapter)
    _, _, Client = platform_module()
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            data = {
                'openai_chat': {'choices': [{'message': {'tool_calls': [{'id': 'call_1', 'function': {'name': 'echo', 'arguments': '{"value":"ping"}'}}]}, 'finish_reason': 'tool_calls'}]},
                'openai_responses': {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'call_1', 'name': 'echo', 'arguments': '{"value":"ping"}'}]},
                'anthropic_messages': {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'call_1', 'name': 'echo', 'input': {'value': 'ping'}}]},
            }[adapter]
        else:
            data = {
                'openai_chat': {'choices': [{'message': {'content': 'ping'}, 'finish_reason': 'stop'}]},
                'openai_responses': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ping'}]}]},
                'anthropic_messages': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'ping'}]},
            }[adapter]
        return httpx.Response(200, json=data)
    result = store.check(model['model_ref'], 'tools', Client(store, transport=httpx.MockTransport(reply)))
    assert result['status'] == 'verified'
    assert len(requests) == 2
    final = json.dumps(requests[1])
    assert 'Call echo with value ping' in final and 'call_1' in final and 'ping' in final
    assert len(json.loads((tmp_path / 'usage.json').read_text())) == 1


def test_request_budget_and_credential_rotation_fail_closed(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    store.authorize(conn['connection_id'], {'roles': ['writer'], 'risk_accepted': True, 'max_requests': 1,
        'expires_at': time.time() + 60}, store.state()['revision'])
    snapshot = store.resolve('writer', model['model_ref'], require_verified=False)
    requests = []
    client = Client(store, transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(401, text='synthetic-canary-platform-key')))
    with pytest.raises(Error, match='CREDENTIAL_REJECTED') as error:
        client.call(snapshot, [{'role': 'user', 'content': 'hello'}])
    assert 'synthetic-canary-platform-key' not in str(error.value)
    with pytest.raises(Error, match='REQUEST_BUDGET_EXHAUSTED'):
        client.call(snapshot, [{'role': 'user', 'content': 'hello'}])
    store.credential(conn['connection_id'], {}, store.state()['revision'], clear=True)
    with pytest.raises(Error, match='CREDENTIAL_CHANGED'):
        client.call(snapshot, [{'role': 'user', 'content': 'hello'}])
    assert len(requests) == 1


def test_windows_secret_ciphertext_and_public_records_never_expose_key(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows DPAPI contract')
    Store, _, _ = platform_module()
    key = 'synthetic-dpapi-canary-12345'
    store = Store(tmp_path)
    conn = store.add_connection({'name': 'secret test', 'base_url': 'https://example.com/v1', 'api_key': key})
    assert store.secrets.read(conn['credential_ref']) == key
    assert key not in json.dumps(store.catalog_rows())
    for file in tmp_path.rglob('*'):
        if file.is_file():
            assert key.encode() not in file.read_bytes()


def test_public_dns_private_target_rejected_before_transport(tmp_path, monkeypatch):
    import socket
    from src.model_platforms.security import pinned_address
    _, Error, _ = platform_module()
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('169.254.169.254', 443))])
    with pytest.raises(Error, match='UNSAFE_DNS_TARGET'):
        pinned_address('https://example.com/v1', 'public')


@pytest.mark.parametrize('adapter', ['openai_chat', 'openai_responses', 'anthropic_messages'])
def test_generation_uses_real_adapter_not_legacy_client(adapter, tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch, adapter)
    from src.model_platforms.integration import configuration
    from src.model_platforms.runtime import RuntimeClient
    from src.llm import generate
    config = configuration(store, store.resolve('writer', model['model_ref'], require_verified=False))
    seen = []
    def request(self, snapshot, path, **kwargs):
        seen.append(kwargs['body'])
        value = '{"title":"具体事件","body":"完整的正文","topics":[]}'
        return {'openai_chat': {'choices': [{'message': {'content': value}, 'finish_reason': 'stop'}]},
            'openai_responses': {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': value}]}]},
            'anthropic_messages': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': value}]}}[adapter]
    monkeypatch.setattr(RuntimeClient, '_request', request)
    monkeypatch.setattr(generate, 'init_chat_model', lambda *args, **kwargs: pytest.fail('Custom adapter must not use legacy client'))
    assert generate.generate_json(config, system_prompt='Only JSON', user_prompt='hello')['title'] == '具体事件'
    assert generate.generate_draft(config, title_hint='事件', prompt_hint='材料', asset_paths=[])['body'] == '完整的正文'
    assert len(seen) == 2


def test_frozen_snapshot_cannot_retarget_credentials_or_expand_budget(tmp_path, monkeypatch):
    import copy
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    original = store.resolve('writer', model['model_ref'], require_verified=False)
    requests = []
    client = Client(store, transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(200, json={})))
    for field, value in [('base_url', 'http://127.0.0.1:19000/v1'), ('upstream_model_id', 'other-model'),
                         ('authorization', {**original['authorization'], 'max_requests': 9999})]:
        tampered = copy.deepcopy(original)
        tampered[field] = value
        with pytest.raises(Error, match='SNAPSHOT_INVALID'):
            client.call(tampered, [{'role': 'user', 'content': 'hi'}])
    assert requests == []


def test_custom_output_failure_is_not_replayed_or_routed_to_legacy(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    from src.model_platforms.integration import configuration
    from src.model_platforms.runtime import RuntimeClient
    from src.model_platforms import PlatformError
    from src.llm.generate import generate_json
    config = configuration(store, store.resolve('writer', model['model_ref'], require_verified=False))
    requests = []
    def fail(*args, **kwargs):
        requests.append(1)
        raise PlatformError('RATE_LIMITED', 'HTTP 429', retryable=True)
    monkeypatch.setattr(RuntimeClient, '_request', fail)
    monkeypatch.setenv('LLM_RATE_LIMIT_RETRY_SECONDS', '0')
    with pytest.raises(PlatformError, match='RATE_LIMITED'):
        generate_json(config, system_prompt='Only JSON', user_prompt='hello')
    assert len(requests) == 1


def test_cli_checkpoint_models_preserve_public_authorization_and_restore_binding(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    from src.model_platforms.integration import checkpoint_models, resume_model_environment
    from src.agent.editorial_agent import _checkpoint_payload
    snapshot = store.resolve('writer', model['model_ref'], require_verified=False)
    env = {'MODEL_PLATFORMS_DIR': str(tmp_path), 'RUN_MODEL_SNAPSHOTS': json.dumps({'writer': snapshot})}
    runtime = checkpoint_models(env)
    payload = _checkpoint_payload({'model_runtime': runtime})
    assert payload['model_runtime']['snapshots']['writer']['authorization'] == snapshot['authorization']
    restored = resume_model_environment(payload, {})
    assert json.loads(restored['RUN_MODEL_SNAPSHOTS'])['writer']['upstream_model_id'] == model['upstream_model_id']
    assert restored['WRITER_MODEL_REF'] == model['model_ref']
    assert restored['MODEL_PLATFORMS_DIR'] == str(tmp_path)
    from src.model_platforms import PlatformError
    with pytest.raises(PlatformError, match='SNAPSHOT_CONFLICT'):
        resume_model_environment(payload, {'WRITER_MODEL_REF': 'm_other'})
    poisoned = json.loads(json.dumps(runtime))
    poisoned['snapshots']['writer']['api_key'] = 'synthetic-checkpoint-canary'
    assert 'synthetic-checkpoint-canary' not in json.dumps(_checkpoint_payload({'model_runtime': poisoned}))


def test_old_custom_checkpoint_cannot_silently_select_new_default(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    from src.model_platforms.integration import resume_model_environment
    from src.model_platforms import PlatformError
    with pytest.raises(PlatformError, match='SNAPSHOT_MISSING'):
        resume_model_environment({'run_id': 'old'}, {'MODEL_PLATFORMS_DIR': str(tmp_path), 'WRITER_MODEL_REF': model['model_ref']})
    assert resume_model_environment({'run_id': 'old'}, {}) == {}


def test_custom_preflight_does_not_authorize_payg_image_balance(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timezone
    from src.workflow import pipeline
    from src.model_platforms.integration import configuration
    from src.model_platforms.preflight import authorized_plan
    store, _, model = configured(tmp_path, monkeypatch)
    config = configuration(store, store.resolve('writer', model['model_ref'], require_verified=False))
    now = datetime.now(timezone.utc)
    record = next(r for r in pipeline.build_subscription_runtime_records('minimax', image_model='image-01', now=now) if r.kind == 'image')
    paid = replace(record, provider='aliyun', cost_class='payg', remaining=100)
    monkeypatch.setattr(pipeline, 'load_quota_records', lambda **kwargs: ([paid], []))
    monkeypatch.setenv('IMAGE_PROVIDER', 'aliyun')
    from src.model_platforms import PlatformError
    with pytest.raises(PlatformError, match='IMAGE_NOT_AUTHORIZED'):
        authorized_plan(config, require_image=True, current=now, quota_dir=tmp_path, provider_keys={})


def test_environment_key_rotation_blocks_old_snapshot_and_authorization(tmp_path, monkeypatch):
    store, conn, model = configured(tmp_path, monkeypatch)
    _, Error, Client = platform_module()
    snapshot = store.resolve('writer', model['model_ref'], require_verified=False)
    monkeypatch.setenv('TEST_PLATFORM_KEY', 'new-synthetic-account-key')
    with pytest.raises(Error, match='CREDENTIAL_CHANGED'):
        store.consume(snapshot)
    with pytest.raises(Error, match='CREDENTIAL_CHANGED'):
        store.resolve('writer', model['model_ref'], require_verified=False)
    store.credential(conn['connection_id'], {'credential_env': 'TEST_PLATFORM_KEY'}, store.state()['revision'])
    with pytest.raises(Error, match='BILLING_NOT_AUTHORIZED'):
        store.resolve('writer', model['model_ref'], require_verified=False)


def test_explicit_legacy_choice_does_not_use_custom_default(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    store, _, model = configured(tmp_path / 'data/model_platforms', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.bind({'writer': model['model_ref']}, store.state()['revision'])
    env = service.freeze_model_roles({}, {'kind': 'auto', 'llm_id': 'minimax:explicit-model'})
    from src.model_platforms.integration import platform_config
    assert platform_config('writer', env=env) is None
    assert json.loads(env['RUN_LEGACY_MODEL_ROLES'])['writer'] == 'minimax:explicit-model'


def test_writer_task_does_not_validate_unused_agent_and_agent_only_authorization_works(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    store, conn, model = configured(tmp_path / 'data/model_platforms', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.bind({'agent': model['model_ref'], 'writer': model['model_ref']}, store.state()['revision'])
    store._mutate(store.state()['revision'], lambda state: state['models'][0]['capabilities'].pop('structured'))
    env = service.freeze_model_roles({}, {'kind': 'auto'})
    assert set(json.loads(env['RUN_MODEL_SNAPSHOTS'])) == {'writer'}
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.bind({'writer': ''}, store.state()['revision'])
    store.authorize(conn['connection_id'], {'roles': ['agent'], 'risk_accepted': True, 'max_requests': 100,
        'expires_at': time.time() + 600}, store.state()['revision'])
    args, env = service.plan({'kind': 'agent', 'agent_id': model['model_ref']}, 'c' * 32)
    assert env['CONTROLLER_MODEL_REF'] == model['model_ref']


def test_compaction_inherits_current_plan_controller(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    store, _, model = configured(tmp_path / 'data/model_platforms', monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    from types import SimpleNamespace
    from src.agent import compaction
    service.conversation_store = SimpleNamespace(save_snapshot=lambda *a: None, get=lambda *a: {})
    monkeypatch.setattr(service, '_read_agent_conversation', lambda *args: {'plans': [{'model_roles': {'agent': model['model_ref']}}]})
    captured = []
    monkeypatch.setattr(compaction, 'compact_conversation', lambda *args, summarize, **kwargs: summarize({}))
    monkeypatch.setattr(compaction, 'minimax_summary', lambda payload, config: captured.append(config) or {})
    service.compact_agent_conversation('a' * 32)
    assert captured[0].platform_snapshot['model_ref'] == model['model_ref']


def test_legacy_controller_keeps_existing_local_file_credentials(monkeypatch):
    from src import config
    from src.model_platforms.integration import legacy_controller
    monkeypatch.setattr(config, '_parse_llm_key_file', lambda path: {'api_key': 'synthetic-file-key', 'model': 'file-model', 'billing_mode': 'subscription_only'})
    controller = legacy_controller({}, provider='minimax')
    assert controller.api_key == 'synthetic-file-key'
    assert controller.model == 'file-model'


def test_v2_roles_are_single_cas_record_not_two_file_projection(tmp_path, monkeypatch, workbench_factory):
    from src.model_platforms.service import platform_request
    service = workbench_factory(tmp_path)
    monkeypatch.setattr(service, 'models', lambda: {'rows': [{'id': 'minimax:model', 'kind': 'llm', 'selectable': True}]})
    store = service.model_platforms()
    platform_request(service, 'PUT', '/api/model-platforms/roles', {'agent': 'minimax:model', 'expected_revision': 0})
    platform_request(service, 'PUT', '/api/model-platforms/roles', {'writer': 'minimax:model', 'expected_revision': 1})
    assert store.state()['roles'] == {'agent': 'minimax:model', 'writer': 'minimax:model'}
    assert not (service.directory / 'providers.json').exists()


def test_proxy_pinned_tls_context_keeps_original_hostname_verification(monkeypatch):
    import ssl
    from src.model_platforms.runtime import OriginTLSContext
    context = OriginTLSContext('api.example.com')
    captured = []
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', lambda self, *args, **kwargs: captured.append(kwargs['server_hostname']))
    context.wrap_socket(object(), server_hostname='8.8.8.8')
    assert captured == ['api.example.com']
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED


def test_cli_freeze_applies_snapshot_not_later_default(tmp_path, monkeypatch):
    store, _, model = configured(tmp_path, monkeypatch)
    _, _, Client = platform_module()
    store.check(model['model_ref'], 'structured', Client(store, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}))))
    store.bind({'agent': model['model_ref'], 'writer': model['model_ref']}, store.state()['revision'])
    from src.model_platforms.integration import freeze_run_environment, platform_config
    env = {'MODEL_PLATFORMS_DIR': str(tmp_path), 'TEST_PLATFORM_KEY': 'synthetic-canary-platform-key'}
    env.update(freeze_run_environment(env))
    store.bind({'agent': '', 'writer': ''}, store.state()['revision'])
    assert platform_config('agent', env=env).platform_snapshot['model_ref'] == model['model_ref']
    assert platform_config('writer', env=env).platform_snapshot['model_ref'] == model['model_ref']


def test_legacy_resume_applies_actual_writer_model_and_checks_all_conflicts(tmp_path, monkeypatch):
    from src.model_platforms.integration import freeze_run_environment, checkpoint_models, resume_model_environment
    from src.config import load_llm_configs
    from src.model_platforms import PlatformError
    env = {'MODEL_PLATFORMS_DIR': str(tmp_path), 'MINIMAX_TOKEN_PLAN_API_KEY': 'synthetic-legacy-key',
           'LLM_PROVIDER': 'minimax', 'MINIMAX_LLM_MODEL': 'original-model'}
    env.update(freeze_run_environment(env))
    checkpoint = {'model_runtime': checkpoint_models(env)}
    changed = {**env, 'MINIMAX_LLM_MODEL': 'changed-model', 'MINIMAX_BASE_URL': 'https://changed.example.com/v1'}
    changed.update(resume_model_environment(checkpoint, changed))
    for name, value in changed.items():
        monkeypatch.setenv(name, value)
    selected = load_llm_configs()[0]
    assert selected.model == 'original-model'
    assert selected.base_url == 'https://api.minimax.cn/v1'
    with pytest.raises(PlatformError, match='SNAPSHOT_CONFLICT'):
        resume_model_environment(checkpoint, {**changed, 'WRITER_MODEL_REF': 'm_other'})


def test_legacy_freeze_keeps_different_controller_and_writer_models(tmp_path, monkeypatch):
    from src.model_platforms.integration import freeze_run_environment, frozen_legacy_config
    env = {'MODEL_PLATFORMS_DIR': str(tmp_path), 'MINIMAX_TOKEN_PLAN_API_KEY': 'synthetic-legacy-key',
           'LLM_PROVIDER': 'minimax', 'AGENT_LLM_MODEL': 'controller-A', 'MINIMAX_LLM_MODEL': 'writer-B'}
    env.update(freeze_run_environment(env))
    assert frozen_legacy_config('agent', env=env).model == 'controller-A'
    assert frozen_legacy_config('writer', env=env).model == 'writer-B'
