"""Explicit LLM authorization is separate from legacy image quota policy."""
from datetime import timedelta
from pathlib import Path
import os

from .security import PlatformError


def authorized_plan(config, *, require_image, current, quota_dir, provider_keys):
    from src.workflow.pipeline import (
        ModelChoice, FreeModelPlan, load_quota_records, build_subscription_runtime_records, _choose_image, SUBSCRIPTION_PROVIDERS,
    )
    snapshot = config.platform_snapshot
    image = None
    provider = os.getenv('IMAGE_PROVIDER', 'auto')
    if require_image and provider not in {'local', 'opencodex'}:
        records, _ = load_quota_records(quota_dir=quota_dir, now=current, max_age=timedelta(hours=2), provider_keys=provider_keys)
        if provider == 'minimax':
            if (not provider_keys.get('minimax') or os.getenv('MINIMAX_BILLING_MODE', 'subscription_only') != 'subscription_only'
                    or any(os.getenv(k, '0').lower() in {'1', 'true', 'yes', 'on'} for k in ('MINIMAX_ALLOW_PAID_CREDITS', 'MINIMAX_ALLOW_PAYGO'))):
                raise PlatformError('IMAGE_BILLING_NOT_AUTHORIZED', 'MiniMax 生图需要有效订阅凭据且关闭按量与充值余额回退')
            records += build_subscription_runtime_records('minimax', image_model=os.getenv('MINIMAX_IMAGE_MODEL') or 'image-01', now=current)
        eligible = [r for r in records if r.kind == 'image' and (provider == 'auto' or r.provider == provider)
                    and (r.cost_class == 'free' or (r.cost_class == 'subscription_included' and r.provider in SUBSCRIPTION_PROVIDERS))]
        requested = os.getenv({'minimax': 'MINIMAX_IMAGE_MODEL', 'aliyun': 'ALIYUN_IMAGE_MODEL',
                               'volcengine': 'VOLCENGINE_IMAGE_MODEL', 'siliconflow': 'SILICONFLOW_IMAGE_MODEL'}.get(provider, ''), '')
        if requested:
            eligible = [r for r in eligible if r.model == requested]
        chosen = _choose_image(eligible, explicit_model=requested)
        if not chosen:
            raise PlatformError('IMAGE_NOT_AUTHORIZED', '没有已授权生图模型，请选择现有免费/订阅生图模型；不自动同步或回退付费')
        image = ModelChoice.from_record(chosen)
    llm = ModelChoice(provider=snapshot['connection_id'], model=snapshot['upstream_model_id'], kind='llm',
                      remaining=0, total=None, unit='费用已授权；平台余额未知',
                      snapshot_path=Path(config.platform_directory) / 'registry.json', captured_at=current,
                      cost_class='explicit_authorization', quota_pool=snapshot['rate_limit_group'])
    return FreeModelPlan(llm=llm, image=image, vision=None)
