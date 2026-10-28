def title(value):
    value = value.strip()
    if not value:
        raise ValueError('blank title')
    return value


def identifier(value):
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 2**63-1:
        raise ValueError('invalid id')
    return int(value)
