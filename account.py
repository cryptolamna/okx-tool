import typing
import time
from datetime import datetime

from httpx import Client

from okx.Funding import FundingAPI
from okx.Account import AccountAPI
from okx.MarketData import MarketAPI
from okx.SubAccount import SubAccountAPI
from okx.NDBroker import NDBrokerAPI
from okx.consts import API_URL

from retry import retry

import utils

LIVE_TRADING_FLAG = '0'


class BrokenResponseError(Exception):
    """Exception raised when okx response is broken"""

    def __init__(self, req: str, resp: typing.Any):
        super().__init__(f'There was error during call {req}: {resp}')


def _fetch_trans_id(response: typing.Dict[str, str | typing.List[dict]] | None) -> str | None:
    """Extract `transId` from funds_transfer response"""
    if not response:
        return None
    if response.get('code', '') != '0':
        raise Exception(response.get('msg', ''))

    transactions = response.get('data', [])
    if not transactions:
        raise BrokenResponseError('funds_transfer', response)

    return transactions[0]['transId']


class OkxAccount(object):
    _funding: FundingAPI
    _account: AccountAPI
    _sub: SubAccountAPI
    _market: MarketAPI
    _broker: NDBrokerAPI

    @staticmethod
    def _httpx_client(proxies: typing.Dict[str, str]):
        return Client(base_url=API_URL, http2=True, proxies=proxies)

    def __init__(self, api_key: str, secret_key: str, passphrase: str, proxy: str = '', debug: bool = False) -> None:
        proxy = utils.make_proxy_dict(proxy)  # Initialize proxy and client
        client = self._httpx_client(proxy)

        self._funding = FundingAPI(
            api_key, secret_key, passphrase, flag=LIVE_TRADING_FLAG, debug=debug)
        self._funding.client = client  # change default client to proxy client

        self._account = AccountAPI(
            api_key, secret_key, passphrase, flag=LIVE_TRADING_FLAG, debug=debug)
        self._account.client = client

        self._sub = SubAccountAPI(
            api_key, secret_key, passphrase, flag=LIVE_TRADING_FLAG, debug=debug)
        self._sub.client = client

        self._broker = NDBrokerAPI(
            api_key, secret_key, passphrase, flag=LIVE_TRADING_FLAG, debug=debug)
        self._broker.client = client

        self._market = MarketAPI(flag=LIVE_TRADING_FLAG, debug=debug)
        self._market.client = client

    @retry(tries=5, delay=2, logger=None)
    def get_assets_prices(self) -> typing.Dict[str, float]:
        """Auxiliary method for filtering assets by balance"""
        assets = self._market.get_tickers(instType='SPOT')['data']

        assets = filter(lambda asset: asset['instId'].endswith('USDT'), assets)

        return {
            asset['instId'].split('-')[0]: float(asset['last']) for asset in assets
        }

    @retry(tries=5, delay=2, logger=None)
    def get_currencies(self, ccy: str = '', can_deposit: bool | None = True, can_withdraw: bool | None = True) -> typing.List[typing.Dict[str, str | int | bool]]:
        """
        Auxiliary method for `min_fee` param
        :param str ccy: currency to get. '' to get all currencies
        :param bool | None can_deposit:
        :param bool | None can_withdraw:
        :return: list of currencies. More information in OKX docs
        """
        currencies = self._funding.get_currencies(ccy)['data']
        if can_withdraw is None and can_deposit is None:
            return currencies
        if can_withdraw is not None:
            currencies = list(
                filter(
                    lambda currency: currency['canWd'] == can_withdraw,
                    currencies
                )
            )
        if can_deposit is not None:
            currencies = list(
                filter(
                    lambda currency: currency['canDep'] == can_deposit,
                    currencies
                )
            )

        return currencies

    @retry(tries=5, delay=2, logger=None)
    def get_sub_list(self, enabled: bool = True, can_trans_out: bool | None = None) -> typing.List[str]:
        """
        Auxiliary method for transferring assets from sub-accounts

        :param bool enabled: True = Normal. False = Frozen
        :param bool | None can_trans_out: True = sub can transfer out. False = can't. None = both can and can't

        :return: list of sub-account labels
        """
        sub_list = self._sub.get_subaccount_list(enable=enabled)['data']

        if can_trans_out is not None:
            return [
                sub['subAcct'] for sub in sub_list if sub['canTransOut'] == can_trans_out
            ]
        else:
            return [
                sub['subAcct'] for sub in sub_list
            ]

    @retry(tries=5, delay=2, logger=None)
    def get_sub_balance(self, sub_name: str, ccy: str = '', only_funding: bool = False) \
            -> typing.Dict[str, typing.Dict[str, float] | None]:
        """
        Method for getting balances(both funding and trading or only funding) on sub-account

        :param str sub_name: sub-account name
        :param str ccy: ccy to get the balance, in case only_funding = False, the balances in trading will be derived in all available currencies. In the case of '' all the balances will be returned
        :param bool only_funding: True = fetch only funding balances. False = both funding and trading

        :return: dict with 2 keys: funding and trading. Values are dicts in format CCY[str]: BALANCE[float]. In case of only_funding "trading" value will be None. Example only_funding = False: {'funding': {'USDT': 127.5}, trading: {}}. Example only_funding = True {'funding': {'USDT': 127.5}, trading: None}
        """
        balance = {
            'funding': None,
            'trading': None
        }

        funding = self._sub.get_funding_balance(sub_name, ccy)['data']
        balance['funding'] = {asset['ccy']: float(asset['availBal']) for asset in
                              funding}  # convert to dict CCY: BALANCE

        if only_funding:
            return balance

        trading = self._sub.get_account_balance(sub_name)['data']
        if len(trading) == 0:
            balance['trading'] = {}
            return balance

        trading = trading[0]['details']
        balance['trading'] = {asset['ccy']: float(asset['availBal']) for asset in
                              trading}  # convert to dict CCY: BALANCE

        return balance

    @retry(tries=5, delay=2, logger=None)
    def get_all_subs_balance(self, enabled: bool = True, can_trans_out: bool | None = None, ccy: str = '',
                             only_funding: bool = False) -> typing.Dict[str, typing.Dict[str, float | dict | None]]:
        """
        Method for getting total balance of all sub-accounts and getting balance of each sub-account

        :param bool enabled: True = Normal. False = Frozen
        :param bool | None can_trans_out: True = sub can transfer out. False = can't. None = both can and can't:
        :param str ccy: ccy to get the balance, in case only_funding = False, the balances in trading will be derived in all available currencies. In the case of '' all the balances will be returned
        :param bool only_funding: True = fetch only funding balances. False = both funding and trading
        :return: dict with 2 keys: total and subs. 'total' value is dict in format CCY[str]: BALANCE[float]. 'subs' values are the same as in 'get_sub_balance' with format SUB_NAME[str]: BALANCES[dict](same as in 'get_sub_balance')
        """
        sub_list = self.get_sub_list(enabled, can_trans_out)

        balances = {
            'total': {},
            'subs': {
                sub: {} for sub in sub_list  # avoid excessive conditions
            },
        }

        for sub in sub_list:
            balances['subs'][sub] = self.get_sub_balance(
                sub, ccy, only_funding)

        for _, balance in balances['subs'].items():
            total = balances['total']
            funding = balance['funding']
            # avoid type error when only_funding = True
            trading = balance.get('trading', {})

            for ccy, avail_bal in funding.items():
                if total.get(ccy):  # to sum
                    total[ccy] += avail_bal
                else:
                    total[ccy] = avail_bal

            for ccy, avail_bal in trading.items():
                if total.get(ccy):  # to sum
                    total[ccy] += avail_bal
                else:
                    total[ccy] = avail_bal

        return balances

    @retry(tries=5, delay=1, logger=None)
    def transfer_from_sub(self, sub_name: str, ccy: str, amt: float | int | str | None = None,
                          from_trading: bool | None = None, to_trading: bool = False) -> typing.List[str] | str | None:
        """
        Method for transferring funds from sub-account both for trading and funding accounts
        :param str sub_name: sub-account name
        :param str ccy: currency to transfer
        :param float | int| str | None amt: amount for transfer. None to entire balance transfer. None by default
        :param bool | None from_trading: transfer from trading account only. None to both accounts transfer. True to only trading. False to only funding. None by default
        :param bool to_trading: transfer to trading master account. False by default
        :return: list of `transId` [str] or one `transId` [str] (when from_trading = None) or None (zero balances; transfer not possible)
        """
        to_account = 6  # funding account id
        if to_trading:
            to_account = 18  # trading account id

        balance = {}
        if amt is None:
            if from_trading is False:
                balance = self.get_sub_balance(
                    sub_name, ccy, only_funding=True)
            else:
                balance = self.get_sub_balance(sub_name, ccy)

        def transfer_from_trading():
            trading_balance = balance.get('trading', {}).get(ccy, amt)
            if not trading_balance:
                return
            self._funding.funds_transfer(
                ccy, trading_balance, 18, to_account, '2', sub_name)

        def transfer_from_funding():
            """Transfer from sub funding"""
            funding_balance = balance.get('funding', {}).get(ccy, amt)
            if not funding_balance:
                return
            self._funding.funds_transfer(
                ccy, funding_balance, 6, to_account, '2', sub_name)

        """_fetch_trans_id(transfer_from_...) - calling `funds_transfer` and extracting transaction id"""
        if from_trading is None:
            trans_ids = [
                _fetch_trans_id(transfer_from_funding()),
                _fetch_trans_id(transfer_from_trading())
            ]
            if trans_ids == [None, None]:
                return None
            if None in trans_ids:
                trans_ids.remove(None)
            return trans_ids
        if from_trading is True:
            return _fetch_trans_id(
                transfer_from_trading()
            )

        if from_trading is False:
            return _fetch_trans_id(
                transfer_from_funding()
            )

    @retry(tries=5, delay=1, logger=None)
    def get_total_balances(self, ccy: str = '', usd_eq: bool = True, with_sub_accounts: bool = True,
                           sub_enabled: bool = True,
                           only_funding: bool = False) -> typing.Dict[str, typing.Dict[str, float | dict | None]]:
        """
        Method for getting total balance of all sub-accounts and main account and getting balance of each account(sub and main)
        :param str ccy: ccy to get the balance, in case only_funding = False, the balances in trading will be derived in all available currencies. In the case of '' all the balances will be returned
        :param bool usd_eq: usd value for each asset in 'total'. True by default
        :param bool with_sub_accounts: with 'True' receives balances also on sub-accounts
        :param bool sub_enabled: get balances on enabled sub-accounts. True = Normal Subs. False = Frozen Subs
        :param bool only_funding: True = fetch only funding balances. False = both funding and trading
        :return: dict with 2 keys: total and subs. 'total' value is dict in format CCY[str]: BALANCE[float] or CCY[str]: {balance: BALANCE[FLOAT], usd: USD_VALUE[FLOAT]}. 'subs' values are the same as in 'get_sub_balance' with format SUB_NAME[str]: BALANCES[dict](same as in 'get_sub_balance'). 'main' value is the same as in 'get_sub_balance' with format {'funding:': dict, 'trading': None or dict(when only_funding = False)}
        """
        prices = None
        if usd_eq:
            prices = self.get_assets_prices()
        balances = {
            'total': {},
        }
        if with_sub_accounts:
            balances = self.get_all_subs_balance(
                ccy=ccy, enabled=sub_enabled, only_funding=only_funding)

        balances['main'] = {
            'funding': None,
            'trading': None
        }

        funding = self._funding.get_balances(ccy)['data']
        balances['main']['funding'] = {asset['ccy']: float(asset['availBal']) for asset in
                                       funding}  # convert to dict CCY: BALANCE

        for asset, avail_bal in balances['main']['funding'].items():
            total = balances['total']
            if total.get(asset):  # to sum
                total[asset] += avail_bal
            else:
                total[asset] = avail_bal

        if only_funding:
            for asset, balance in balances['total'].items():
                if not usd_eq:
                    continue
                balances['total'][asset] = {
                    'balance': balance,
                    'usd': balance * prices.get(asset, 0)
                }
            return balances

        trading = self._account.get_account_balance(ccy)['data']
        if len(trading) == 0:
            balances['main']['trading'] = {}
            return balances

        trading = trading[0]['details']
        balances['main']['trading'] = {asset['ccy']: float(asset['availBal']) for asset in
                                       trading}  # convert to dict CCY: BALANCE

        for asset, avail_bal in balances['main']['trading'].items():
            total = balances['total']
            if total.get(asset):  # to sum
                total[asset] += avail_bal
            else:
                total[asset] = avail_bal

        for asset, balance in balances['total'].items():
            if not usd_eq:
                continue
            balances['total'][asset] = {
                'balance': balance,
                # non-tradable assets prices will be 0
                'usd': balance * prices.get(asset, 0)
            }

        return balances

    @retry(tries=5, delay=1, logger=None)
    def transfer_from_trading(self, ccy: str, amt: float | str | int | None = None) -> str | None:
        """
        Method for transferring funds on main account from trading account to funding
        :param str ccy: currency to transfer
        :param float | str | int | None amt: amount to transfer. When `None` entire balance will be transferred
        :return: `transId` or None. None when there's nothing to transfer
        """
        if amt is None:
            trading = self._account.get_account_balance(ccy)['data']
            if len(trading) == 0:
                return None

            trading = trading[0]['details']
            balances = {asset['ccy']: float(asset['availBal']) for asset in
                        trading}  # convert to dict CCY: BALANCE
            amt = balances.get(ccy, 0)
        if not amt:
            return None

        transaction = self._funding.funds_transfer(
            ccy, amt, 18, 6)  # 18 - from trading; 6 - to funding

        return _fetch_trans_id(transaction)

    @retry(tries=5, delay=1, logger=None)
    def withdraw(self, addr: str, ccy: str, chain: str, amt: float | str | int | None = None,
                 min_fee: str | None = None) -> str:
        """
        Method for withdrawing to blockchain
        :param str addr: wallet address to withdraw
        :param str ccy: currency to withdraw
        :param str chain: chain to withdraw
        :param float | str | int| None amt: amount to withdraw. If None entire balance will be withdrawn
        :param str | None min_fee: min_fee to withdraw. If None min_fee will be got from `get_currencies` method
        :return: `withdrawId`
        """
        if min_fee is None:
            currency = self.get_currencies(ccy)[0]
            min_fee = currency.get('minFee', '')

        if amt is None:
            funding = self._funding.get_balances(ccy)['data']
            balances = {asset['ccy']: float(asset['availBal']) for asset in
                        funding}  # convert to dict CCY: BALANCE
            amt = balances.get(ccy, 0)

        result = self._funding.withdrawal(
            ccy, amt, 4, addr, min_fee, f'{ccy}-{chain}')
        if result.get('code', '') != '0':
            raise Exception(result.get('msg', ''))

        result = result['data']
        if len(result) < 1:
            raise Exception('No withdraw')

        return result[0].get('wdId', '')

    @retry(tries=5, delay=1, logger=None)
    def cancel_withdrawal(self, wd_id: str) -> bool:
        """
        Method for cancelling withdraw
        :param str wd_id: `withdrawId` from `withdraw` method
        :return: result of cancellation. True - successful. False - unsuccessful
        """
        return self._funding.cancel_withdrawal(wd_id).get('code', '') == '0'

    @retry(tries=5, delay=1, logger=None)
    def withdrawal_history(self, ccy: str = '', chain: str | None = None, before: str | datetime = '',
                           after: str | datetime = '') -> typing.List[typing.Dict[str | any]]:
        """
        Get withdrawal history on main account
        :param str ccy: currency to get withdraw history. '' to get all withdrawals
        :param str | None chain: chain to filter. If None all withdrawals will be got
        :param str | datetime before: time to filter
        :param str | datetime after: time to filter
        :return: list of withdrawals. Same as OKX Docs
        """
        if before is datetime:
            before = int(time.mktime(before.timetuple()) * 1000)
        if after is datetime:
            after = int(time.mktime(after.timetuple()) * 1000)
        history = self._funding.get_withdrawal_history(
            ccy,
            after=str(after),
            before=str(before),
        )['data']

        if chain is not None:
            history = list(
                filter(
                    lambda withdrawal: chain in withdrawal['chain'].split(
                        '-')[-1],
                    history
                )
            )

        return history

    @retry(tries=5, delay=1, logger=None)
    def deposit_address(self, ccy: str, chain: str | None = None) -> typing.List[typing.Dict[str | typing.Any] | str]:
        """
        Method for getting deposit addresses on main account
        :param str ccy: currency to get dep. address
        :param str | None chain: filter by chain. If None all chains will be returned
        :return: If chain is None will be returned list of addresses as OKX return. If chain is some will be returned list of addresses e.g [0x00..01, 0x00..02, 0x00..03]
        """
        addresses = self._funding.get_deposit_address(ccy)['data']

        if chain is not None:
            addresses = filter(
                lambda address: address['chain'].replace(
                    f'{ccy}-', '') == chain,
                addresses
            )

            return list(
                map(
                    lambda address: address['addr'],
                    addresses
                )
            )

        return addresses
