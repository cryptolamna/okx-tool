import typing

from web3 import Web3, HTTPProvider
from web3.eth import Contract
from web3.types import ChecksumAddress, Wei

from retry import retry

from consts import TOKEN_ABI


class Wallet:
    _pk: str
    _addr: ChecksumAddress
    _rpc: Web3

    _tokens: typing.Dict[ChecksumAddress, Contract] = {}

    def __init__(self, rpc_url: str, private_key: str, default_headers: dict | None = None, proxies: dict | None = None) -> None:
        if proxies is None:
            proxies = {}
        if default_headers is None:
            default_headers = {}

        self._rpc = Web3(HTTPProvider(rpc_url, request_kwargs={"headers": default_headers, "proxies": proxies}))
        self._pk = private_key
        self._addr = self._rpc.eth.account.from_key(private_key).address

    @retry(tries=15, delay=5, logger=None)
    def get_nonce(self):
        return self._rpc.eth.get_transaction_count(self._addr)

    @property
    def address(self) -> ChecksumAddress:
        """
        Get address of wallet
        :return: ChecksumAddress(wallet address)
        """
        return self._addr

    @retry(tries=15, delay=4.5, logger=None)
    def balance(self, token: str | ChecksumAddress | None = None) -> Wei:
        """

        :param str | ChecksumAddress | None token: None - eth. Address | str - erc20 token
        :return: balance in wei
        """
        if token is None:
            return self._rpc.eth.get_balance(self._addr)
        token_address = self._rpc.to_checksum_address(token)
        if token_address in self._tokens:
            token = self._tokens[token_address]
        else:
            token = self._rpc.eth.contract(token_address, abi=TOKEN_ABI)
            self._tokens[token_address] = token

        return token.functions.balanceOf(self._addr).call()

    def _transfer_native(self, amount: Wei, to: ChecksumAddress):
        """

        :param amount:
        :param to:
        :return:
        """
        tx = {
            'type': '0x2',
            'from': self._addr,
            'to': to,
            'value': amount,
            'nonce': self.get_nonce(),
        }

        signed_tx = self._rpc.eth.sign_transaction(tx, self._pk)

        return signed_tx.rawTransaction

    def _transfer_token(self, token: ChecksumAddress, amount: Wei, to: ChecksumAddress):
        """

        :param token:
        :param amount:
        :param to:
        :return:
        """
        token = self._tokens[token]

        tx = token.functions.transfer(to, amount).buildTransaction({
            'type': '0x2',
            'from': self._addr,
            'nonce': self.get_nonce(),
        })

        signed_tx = self._rpc.eth.sign_transaction(tx, self._pk)

        return signed_tx.rawTransaction

    @retry(tries=15, delay=5, logger=None)
    def transfer(self, amount: Wei, to: ChecksumAddress | str, token: str | ChecksumAddress | None = None):
        """

        :param amount:
        :param to:
        :param token:
        :return:
        """
        if token is None:
            raw_tx = self._transfer_native(amount, self._rpc.to_checksum_address(to))
        else:
            token_address = self._rpc.to_checksum_address(token)
            if token_address not in self._tokens:
                token = self._rpc.eth.contract(token_address, abi=TOKEN_ABI)
                self._tokens[token_address] = token

            raw_tx = self._transfer_token(token_address, amount, to)

        return self._rpc.eth.send_raw_transaction(raw_tx)
