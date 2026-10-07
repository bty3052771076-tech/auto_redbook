"""Model administration without a web server or command-line secret values."""
import json
import os
import time
from pathlib import Path

import typer

from .presets import PRESETS
from .runtime import RuntimeClient
from .store import PlatformStore

app = typer.Typer(help='管理模型连接、目录与角色；测试调用需要显式费用授权。')


def store():
    return PlatformStore(os.getenv('MODEL_PLATFORMS_DIR') or Path.cwd() / 'data/model_platforms',
                         namespace=os.getenv('MODEL_PLATFORMS_NAMESPACE', 'workflow'))


def output(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.command('list')
def connections():
    output(store().catalog_rows())


@app.command('presets')
def presets():
    output(PRESETS)


@app.command('add')
def add(name: str, base_url: str, adapter: str = 'openai_chat', credential_env: str = '', local: bool = False,
        no_auth: bool = False, auth_mode: str = ''):
    current = store()
    output(current.add_connection({'name': name, 'base_url': base_url, 'adapter': adapter,
        'credential_env': credential_env, 'network': 'local' if local else 'public',
        'auth_mode': 'none' if no_auth else auth_mode or ('x-api-key' if adapter == 'anthropic_messages' else 'bearer')}))


@app.command('enable-model')
def enable_model(model_ref: str, enabled: bool = True):
    current = store()
    output(current.edit_model(model_ref, {'enabled': enabled}, current.state()['revision']))


@app.command('models')
def models(connection_id: str = '', model_id: str = ''):
    current = store()
    if model_id:
        output(current.add_model({'connection_id': connection_id, 'upstream_model_id': model_id, 'enabled': True}, current.state()['revision']))
    else:
        output(current.catalog_rows()['models'])


@app.command('authorize')
def authorize(connection_id: str, roles: str = 'agent,writer', max_requests: int = 100, hours: int = 24,
              accept_cost_risk: bool = False):
    current = store()
    output(current.authorize(connection_id, {'roles': roles.split(','), 'max_requests': max_requests,
        'expires_at': time.time() + hours * 3600, 'risk_accepted': accept_cost_risk}, current.state()['revision']))


@app.command('discover')
def discover(connection_id: str):
    current = store()
    output(current.discover(connection_id, RuntimeClient(current)))


@app.command('check')
def check(model_ref: str, purpose: str = 'text'):
    current = store()
    output(current.check(model_ref, purpose, RuntimeClient(current)))


@app.command('roles')
def roles(role: str = '', model_ref: str = ''):
    current = store()
    output(current.bind({role: model_ref}, current.state()['revision']) if role else current.state()['roles'])


@app.command('resolve')
def resolve(role: str = 'writer', model_ref: str = ''):
    output(store().resolve(role, model_ref))
