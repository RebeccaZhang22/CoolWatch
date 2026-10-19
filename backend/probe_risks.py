"""Shared active-risk contract for probe servers and their HTTP adapter."""
RISK_NAMES = {
    'harmful': '有害行为',
    'prompt_leakage': 'Prompt Leakage（提示信息泄露）',
    'ipi': '间接提示注入',
}
DEFAULT_ENABLED_RISKS = 'ipi'


def parse_enabled_risks(value=DEFAULT_ENABLED_RISKS):
    values = value.split(',') if isinstance(value, str) else list(value)
    enabled = {v.strip() for v in values}
    if not enabled or not enabled <= RISK_NAMES.keys():
        raise ValueError('Enabled probe risks must be a non-empty subset of: ' + ','.join(RISK_NAMES))
    return tuple(risk for risk in RISK_NAMES if risk in enabled)


def risk_selection(enabled):
    return dict(enabled_risks=list(enabled), disabled_risks=[r for r in RISK_NAMES if r not in enabled])
