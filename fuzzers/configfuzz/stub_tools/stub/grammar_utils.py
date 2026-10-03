import json
import logging


# Parameter connector decides how a parameter is written. `-f=flv` takes 1 arg and `-f flv` takes 2 args.
def is_space_connected(grammar: json) -> bool:
    connector = grammar['connector']
    if connector == ' ':
        return True
    if connector == '=':
        return False
    logging.error(f'unsupported parameter connector: {connector}')
    exit(0)


def cmd_line(grammar: json) -> list[str]:
    return grammar['cmdline'].split(' ')


def opts_num(grammar: json) -> int:
    return len(grammar['options'])


