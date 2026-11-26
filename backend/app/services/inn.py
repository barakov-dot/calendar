"""Контрольные цифры ИНН: защита от опечаток при ручном вводе."""

_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    if not (inn.isascii() and inn.isdigit()):
        return False
    digits = [int(char) for char in inn]
    if len(digits) == 10:
        return digits[9] == _check_digit(digits, _WEIGHTS_10)
    if len(digits) == 12:
        return digits[10] == _check_digit(digits, _WEIGHTS_11) and digits[11] == _check_digit(
            digits, _WEIGHTS_12
        )
    return False


def with_check_digits(base: str) -> str:
    """Дополняет 9 или 10 цифр контрольными (для тестовых данных)."""
    digits = [int(char) for char in base]
    weights = (_WEIGHTS_10,) if len(digits) == 9 else (_WEIGHTS_11, _WEIGHTS_12)
    for item in weights:
        digits.append(_check_digit(digits, item))
    return "".join(map(str, digits))
