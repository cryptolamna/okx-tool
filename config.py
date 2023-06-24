import random
import typing
from typing import NamedTuple

from yaml import safe_load


class OkxConfig(NamedTuple):
    api_key: str
    secret_key: str
    passphrase: str

    proxy: str

    use_subs: bool
    only_funding: bool

    amounts: typing.List[float] | float | int
    delays: typing.List[int] | int

    def amount(self):
        return random.uniform(self.amounts[0], self.amounts[1])

    def delay(self):
        return random.randint(self.delays[0], self.delays[1])


class EvmConfig(NamedTuple):
    rpc_url: str
    default_headers: str


class GeneralConfig(NamedTuple):
    okx: OkxConfig
    evm: EvmConfig
    working_dir: str


def read_config(filename: str) -> GeneralConfig:
    content = open(filename)
    parsed = safe_load(content)

    evm_config = parsed['evm']
    okx_config = parsed['okx']

    amounts = okx_config['amounts']
    if type(amounts) is not list:
        amounts = [float(amounts), float(amounts)]

    delays = okx_config['delays']
    if type(delays) is not list:
        delays = [int(delays), int(delays)]

    okx = OkxConfig(
        okx_config['api-key'],
        okx_config['secret-key'],
        okx_config['passphrase'],
        okx_config.get('proxy', ''),
        okx_config.get('use-subs', True),
        okx_config.get('only-funding', False),
        amounts,
        delays
    )

    evm = EvmConfig(
        evm_config['rpc-url'],
        evm_config.get('default-headers')
    )

    return GeneralConfig(
        okx,
        evm,
        parsed.get('working-dir', './')
    )
