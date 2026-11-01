"""Proof-of-work против ботов в формате ALTCHA: задача подписана HMAC, решение ищет браузер.

Сервер загадывает число n и отдаёт sha256(salt + n), соль и подпись. Браузер перебирает
числа до совпадения. Состояния нет: всё нужное для проверки — в подписанной задаче,
повторное использование ловит хранилище по самой задаче.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

ALGORITHM = "SHA-256"
CHALLENGE_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class Challenge:
    algorithm: str
    challenge: str
    salt: str
    signature: str
    maxnumber: int


@dataclass(frozen=True)
class Solved:
    challenge: str
    expires_at: int


def derive_key(secret: str) -> bytes:
    """Ключ подписи из уже существующего секрета, чтобы не заводить новый в Vault."""
    return hashlib.sha256(f"altcha-pow:{secret}".encode()).digest()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sign(key: bytes, challenge: str) -> str:
    return hmac.new(key, challenge.encode(), hashlib.sha256).hexdigest()


def create_challenge(key: bytes, now: datetime, maxnumber: int, number: int | None = None) -> Challenge:
    """Новая задача; срок годности зашит в соль и поэтому тоже под подписью."""
    expires = int((now + CHALLENGE_TTL).timestamp())
    salt = f"{secrets.token_hex(12)}?expires={expires}"
    secret_number = secrets.randbelow(maxnumber + 1) if number is None else number
    challenge = sha256_hex(f"{salt}{secret_number}")
    return Challenge(ALGORITHM, challenge, salt, sign(key, challenge), maxnumber)


def solve(challenge: Challenge) -> int | None:
    """Перебор, как в браузере; нужен тестам."""
    for number in range(challenge.maxnumber + 1):
        if sha256_hex(f"{challenge.salt}{number}") == challenge.challenge:
            return number
    return None


def encode_payload(challenge: Challenge, number: int) -> str:
    body = {
        "algorithm": challenge.algorithm, "challenge": challenge.challenge, "number": number,
        "salt": challenge.salt, "signature": challenge.signature,
    }
    return base64.b64encode(json.dumps(body).encode()).decode()


def expires_at(salt: str) -> int | None:
    _, _, query = salt.partition("?")
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name == "expires" and value.isdigit():
            return int(value)
    return None


def verify_payload(key: bytes, payload: str, now: datetime) -> Solved | None:
    """Проверяет решение; возвращает задачу и её срок (для учёта повторов) или None."""
    try:
        data = json.loads(base64.b64decode(payload, validate=True))
        algorithm, challenge, salt = data["algorithm"], data["challenge"], data["salt"]
        number, signature = int(data["number"]), data["signature"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        return None
    if algorithm != ALGORITHM or not all(isinstance(v, str) for v in (challenge, salt, signature)):
        return None
    expires = expires_at(salt)
    if expires is None or expires < now.timestamp():
        return None
    if not hmac.compare_digest(sign(key, challenge), signature):
        return None
    if not hmac.compare_digest(sha256_hex(f"{salt}{number}"), challenge):
        return None
    return Solved(challenge, expires)
