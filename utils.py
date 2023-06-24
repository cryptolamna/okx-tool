import time
from os import listdir
import threading

import beaupy
import typing
import httpx
import rich


def make_proxy_dict(raw_proxy: str) -> typing.Dict[str, str]:
    raw_proxy = raw_proxy.strip()
    if not raw_proxy:
        return {}

    return {
        'http': f'http://{raw_proxy}',
        'https': f'https://{raw_proxy}'
    }


def parse_proxy(raw_proxy: str) -> str | None:
    data = raw_proxy.split(':')
    if len(data) == 4:
        return f'{data[0]}:{data[1]}@{data[2]}:{data[3]}'
    if len(data) == 2:
        return raw_proxy
    if '@' in raw_proxy:
        return raw_proxy

    return None


def check_proxy(proxy: str | None) -> bool:
    if not proxy:
        return False
    try:
        response = httpx.get('https://eth0.me/', proxies='http://' + proxy, timeout=15).text.strip()

        return response in proxy
    except (Exception,) as exp:
        print(exp)
        return False


def get_files(directory: str = './', extension: str = '.txt') -> typing.List[str]:
    return list(filter(lambda f: f.endswith(extension) and f != 'requirements.txt', listdir(directory)))


def select_file(msg: str = 'Choose file', directory: str = './', extension: str = '.txt') -> str:
    rich.print(msg)
    files = get_files(directory, extension)
    if len(files) == 0:
        rich.print('[bold red]There are no files to select[/bold red]')
        return ''

    return beaupy.select(options=files, strict=True, cursor_style='orange1')


def load_private_keys(file: str) -> typing.List[str]:
    return [
        pk.strip().replace('0x', '') for pk in open(file) if len(pk.strip().replace('0x', '')) == 64
    ]


def load_addresses(file: str) -> typing.List[str]:
    return [
        address.strip() for address in open(file) if len(address.strip()) == 42
    ]


def load_proxies(file: str) -> typing.List[str]:
    proxies = []
    for raw_proxy in open(file):
        proxy = parse_proxy(raw_proxy.strip())
        if not proxy:
            continue
        proxies.append(proxy)
    return proxies


def check_proxies(proxies: typing.List[str]) -> typing.List[str]:
    valid = []

    def check_func(raw_proxy: str):
        if check_proxy(raw_proxy):
            valid.append(raw_proxy)
    threads = []
    for proxy in proxies:
        threads.append(threading.Thread(target=check_func, args=(proxy,)))

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    return valid
