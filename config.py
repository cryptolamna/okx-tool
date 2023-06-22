from typing import NamedTuple

from yaml import safe_load


class OkxConfig(NamedTuple):
    api_key: str
    secret_key: str
    passphrase: str

    proxy: str

    use_subs: bool
    only_funding: bool


class EvmConfig(NamedTuple):
    rpc_url: str
    default_headers: str


class GeneralConfig(NamedTuple):
    okx: OkxConfig
    evm: EvmConfig


def read_config(filename: str) -> GeneralConfig:
    content = open(filename)
    parsed = safe_load(content)

    evm_config = parsed['evm']
    okx_config = parsed['okx']

    okx = OkxConfig(
        okx_config['api-key'],
        okx_config['secret-key'],
        okx_config['passphrase'],
        okx_config.get('proxy', ''),
        okx_config.get('use-subs', True),
        okx_config.get('only-funding', False),
    )

    evm = EvmConfig(
        evm_config['rpc-url'],
        evm_config.get('default-headers')
    )

    return GeneralConfig(
        okx,
        evm
    )
