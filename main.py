import logging

from datetime import datetime
from rich.console import Console

from config import *
from account import OkxAccount
from wallet import Wallet
from utils import *

FORMAT = '%(asctime)s %(name)s %(levelname)s %(message)s'
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[logging.FileHandler('log.log', mode='a')]
)

console = Console()


def deposit(wk_dir: str, evm: EvmConfig):
    pk_file = select_file('Choose file with [bold orange1 u]private-keys:[/bold orange1 u]', directory=wk_dir)
    if pk_file == '':
        return

    private_keys = load_private_keys(wk_dir + '/' + pk_file)
    logging.info(f'Selected {pk_file} as private-keys. Total pks: {len(private_keys)}')
    console.print(f'Total private-keys: [bold orange1]{len(private_keys)}[/bold orange1]')

    proxies = []
    if beaupy.confirm('Use [u]proxies[/u]?', cursor_style='orange1'):
        proxy_file = select_file('Choose file with [bold orange1 u]proxies:[/bold orange1 u]', directory=wk_dir)
        if proxy_file == '':
            return
        proxies = load_proxies(wk_dir + '/' + proxy_file)
        logging.info(f'Selected {proxy_file} as proxies. Proxies in file: {len(proxies)}')

        proxies = check_proxies(proxies)
        logging.info(f'Valid proxies amt: {len(proxies)}')
    console.print(f'Total proxies: [bold orange1]{len(proxies)}[/bold orange1]')


def withdraw(wk_dir: str, okx_config: OkxConfig):
    file = select_file('Choose file with addresses:', directory=wk_dir)
    if file == '':
        return
    logging.info(f'Selected {file} as addresses')

    addresses = load_addresses(wk_dir + '/' + file)
    if len(addresses) == 0:
        console.print(f'[bold red]There are no addresses to withdraw![/bold red]')
        return
    console.print(f'Total wallets: [bold orange1]{len(addresses)}[/bold orange1]')

    proxy = ''
    if okx_config.proxy is not None:
        proxy = parse_proxy(okx_config.proxy.strip())
        if not check_proxy(proxy):
            console.log('Invalid/broken proxy. OKX will work without proxy')
            logging.warning(f'Broken proxy: {proxy}')
            proxy = ''

    okx = OkxAccount(okx_config.api_key, okx_config.secret_key, okx_config.passphrase, proxy)
    try:
        currencies = okx.get_currencies(can_deposit=None, can_withdraw=True)
    except (Exception,) as exp:
        console.print_exception()
        console.print('[bold red]Failed to load your OKX account[/bold red]')
        logging.error(str(exp))
        return

    try:
        balances = okx.get_total_balances(with_sub_accounts=okx_config.use_subs, only_funding=okx_config.only_funding)
    except (Exception,) as exp:
        console.print_exception()
        console.print('[bold red]Failed to load your OKX balances[/bold red]')
        logging.error(str(exp))
        return

    total = balances['total']
    options = []
    for ccy in total:
        balance = total[ccy]

        if balance['usd'] < 1.:
            continue
        options.append(f"{balance['balance']} - {ccy} ({round(balance['usd'], 2)}$)")

    console.print('Choose [u]currency[/u] to withdraw:')
    ccy = beaupy.select(options, cursor_style='orange1', return_index=True, strict=True)

    ccy = options[ccy].split(' - ')[-1].split()[0]

    logging.info(f'Selected: {ccy}')

    chains = {chain['chain']: chain['minFee'] for chain in currencies if chain['ccy'] == ccy}
    options = []
    for chain, min_fee in chains.items():
        options.append(f'{chain.replace(ccy + "-", "")} | Fee: {min_fee} {ccy}')
    chain = beaupy.select(options, cursor_style='orange1', return_index=False, strict=True)

    chain = f'{ccy}-{chain.split(" | ")[0]}'
    min_fee = chains[chain]

    logging.info(f'Selected {chain} with fee: {min_fee}')

    if okx_config.use_subs:
        console.print('Transferring from sub-accounts..')
        for sub_name in balances['subs'].keys():
            sub_balance = balances['subs'][sub_name]
            funding = sub_balance['funding']
            trading = sub_balance['trading']
            funding_bal = funding.get(ccy, 0)
            logging.info(f'Trying to transfer from sub: {sub_name} to funding balance')
            if funding_bal > 0:
                logging.info(f'Trying to transfer from sub: {sub_name} funding to main funding balance')
                okx.transfer_from_sub(sub_name, ccy, amt=funding_bal, from_trading=False, to_trading=False)
                time.sleep(2)
            if trading is not None:
                trading_bal = trading.get(ccy, 0)
                if trading_bal > 0:
                    logging.info(f'Trying to transfer from sub: {sub_name} trading to main funding balance')
                    okx.transfer_from_sub(sub_name, ccy, amt=funding_bal, from_trading=True, to_trading=False)
                    time.sleep(2)

    trading_balance = balances['main']['trading']
    if trading_balance is not None:
        balance = trading_balance.get(ccy, 0)
        if balance > 0:
            console.print('Transferring from trading account...')
            logging.info(f'Trying to transfer from trading to  funding balance')
            okx.transfer_from_trading(ccy, balance)

    for wallet in addresses:
        amount = okx_config.amount()
        delay = okx_config.delay()

        logging.info(f'{wallet} > Start withdraw {amount} {ccy} to chain {chain} with min_fee: {min_fee}')
        console.print(f'{wallet} > Start withdraw [bold orange1]{round(amount, 6)}[/bold orange1] {ccy}')

        try:
            trans_id = okx.withdraw(wallet, ccy, chain, amount, min_fee)
            logging.info(f'{wallet} > Made withdrawal request. Transaction ID: {trans_id}')
            console.print(f'[yellow]{datetime.now().strftime("%H:%M:%S")}[/yellow] |{wallet} > Made withdrawal request. Transaction ID: [green]{trans_id}[/green]. Waiting [bold orange1]{delay}[/bold orange1] secs.')
            time.sleep(delay)
        except (Exception, ) as exp:
            logging.warning(f'{wallet} > Some exception when making withdrawal request. Error: {str(exp)}')
            console.print(f'{wallet} > Failed to withdraw: [red]{str(exp)}[/red]. Account will be skipped.')
            continue


def main():
    try:
        config = read_config('config.yml')
    except (Exception,):
        console.print_exception()
        return
    logging.info('Config read successful')
    console.print('Choose [u]action[/u]:')
    options = ['Deposit to OKX', 'Withdraw from OKX']
    choice = beaupy.select(options, strict=True, cursor_style='orange1')
    if choice == options[0]:
        deposit(config.working_dir, config.evm)
    else:
        withdraw(config.working_dir, config.okx)

    console.print('Done.')
    time.sleep(60 * 60 * 24)


if __name__ == "__main__":
    main()
