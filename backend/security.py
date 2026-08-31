"""安全模块：密码哈希 + JWT 签发/校验（纯标准库实现，零额外依赖）。

设计：
- 密码哈希：PBKDF2-HMAC-SHA256（stdlib hashlib），每用户随机盐，格式 `salt$hash`。
- JWT：标准 HS256（header.payload.signature，base64url），stdlib hmac 实现。
  不引入 pyjwt/passlib —— 答辩演示环境零配置、免安装，且与项目「零依赖演示」基调一致。

密钥与有效期：
- 密钥来自 settings.auth_secret（config.py，可在 .env 覆盖）。
- 有效期 settings.token_expire_minutes（默认 7 天）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from .config import settings


# ---------- 密码哈希（PBKDF2-HMAC-SHA256） ----------

_PBKDF2_ROUNDS = 120_000


def hash_password(password: str) -> str:
    """返回 `salt$hash`（salt 为随机 16 字节，base64 编码）。"""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；存储格式不符合时安全地返回 False。"""
    try:
        salt_b64, hash_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return hmac.compare_digest(digest, expected)


# ---------- JWT（HS256，纯 stdlib） ----------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_access_token(user_id: int) -> str:
    """签发 HS256 JWT：payload 含 sub(=user_id)、iat、exp。"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + settings.token_expire_minutes * 60,
    }
    head_enc = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    pay_enc = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head_enc}.{pay_enc}".encode("ascii")
    sig = hmac.new(settings.auth_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_enc = _b64url_encode(sig)
    return f"{head_enc}.{pay_enc}.{sig_enc}"


def decode_access_token(token: str) -> int | None:
    """校验 JWT；失败或已过期返回 None。成功返回 user_id。"""
    try:
        head_enc, pay_enc, sig_enc = token.split(".", 2)
        signing_input = f"{head_enc}.{pay_enc}".encode("ascii")
        expected_sig = hmac.new(
            settings.auth_secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(
            _b64url_decode(sig_enc), expected_sig
        ):
            return None
        payload = json.loads(_b64url_decode(pay_enc))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return int(payload.get("sub", 0))
    except Exception:
        return None