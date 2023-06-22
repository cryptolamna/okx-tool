import typing


def make_proxy_dict(raw_proxy: str) -> typing.Dict[str, str]:
    raw_proxy = raw_proxy.strip()
    if not raw_proxy:
        return {}

    return {
        'http': f'http://{raw_proxy}',
        'https': f'https://{raw_proxy}'
    }
