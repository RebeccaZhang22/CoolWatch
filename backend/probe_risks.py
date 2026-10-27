"""Shared active-risk contract for probe servers and their HTTP adapter.

一条部署可以挂多类风险，但每个检测服务实例只负责其中一类：
inscope-service 的一个实例 = 一个探针 checkpoint = 一类风险。
聚合与合并发生在适配层（见 watchers/probe_bank.py），不要求服务端支持多风险。
"""
RISK_NAMES = {
    'harmful': '有害行为',
    'prompt_leakage': 'Prompt Leakage（提示信息泄露）',
    'ipi': '间接提示注入',
}
DEFAULT_ENABLED_RISKS = 'ipi'
# 旧协议（自带 Probe Bank）默认端口。单实例只服务一类风险，多类要各占一个端口。
DEFAULT_RISK_PORT = {'harmful': 8301, 'prompt_leakage': 8303, 'ipi': 8302}


def parse_enabled_risks(value=DEFAULT_ENABLED_RISKS):
    values = value.split(',') if isinstance(value, str) else list(value)
    enabled = {v.strip() for v in values}
    if not enabled or not enabled <= RISK_NAMES.keys():
        raise ValueError('Enabled probe risks must be a non-empty subset of: ' + ','.join(RISK_NAMES))
    return tuple(risk for risk in RISK_NAMES if risk in enabled)


def risk_selection(enabled):
    return dict(enabled_risks=list(enabled), disabled_risks=[r for r in RISK_NAMES if r not in enabled])


def parse_risk_endpoints(value):
    """Parse per-risk service addresses into an ordered {risk: base_url} mapping.

    Format: ``risk=url[,risk=url...]``. Only risks this deployment actually enables
    belong here; a missing entry is fine (that endpoint just isn't checked).
    Unknown risk keys or malformed entries are rejected rather than skipped, so a
    typo can't silently disable a probe.
    """
    endpoints = {}
    for chunk in (value or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, separator, url = chunk.partition('=')
        key, url = key.strip(), url.strip().rstrip('/')
        if not separator or not key or not url:
            raise ValueError(f'Malformed probe bank endpoint {chunk!r}; expected risk=url')
        if key not in RISK_NAMES:
            raise ValueError(f'Unknown probe risk {key!r}; expected one of: ' + ','.join(RISK_NAMES))
        if key in endpoints:
            raise ValueError(f'Duplicate probe bank endpoint for risk {key!r}')
        if not url.startswith(('http://', 'https://')):
            raise ValueError(f'Probe bank endpoint for {key!r} must be an http(s) URL: {url!r}')
        endpoints[key] = url
    return endpoints
