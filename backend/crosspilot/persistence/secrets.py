"""模型配置中敏感字段（API Key）的加密存储。

为什么不用 cryptography 库：
本项目定位是「单机可跑、依赖尽量少」，因此只用**标准库**实现认证加密：
- 密钥派生：``hashlib.scrypt``（成本参数可调，抵抗暴力破解）
- 加密：``hmac`` 实现「计数器模式的一次性密钥流」+ HMAC-SHA256 完整性校验
  （即 encrypt-then-MAC，先加密再对密文做 MAC，防止篡改）

这不是通用加密库的替代品，但对「保护一个存放在本机数据库里的 API Key，
防止数据库文件被直接拷走时泄露明文」这个场景是充分的。**它挡不住已经拿到
本机账户权限的攻击者**——这一点在 README 里明确写了。

格式：``v1:<base64(nonce || ciphertext || mac)>``
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

ENV_SECRET = "CROSSPILOT_SECRET_KEY"
SECRET_FILE = ".secret_key"
_VERSION_PREFIX = "v1:"
_NONCE_BYTES = 16
_KDF_SALT = b"crosspilot-model-settings-v1"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_BYTES = 64  # 前 32 字节加密，后 32 字节做 MAC


class SecretError(RuntimeError):
    """密钥加载/解密失败。解不开就明确报错，绝不当成空值继续跑。"""


def derive_key(material: bytes) -> bytes:
    """把口令/随机字节派生成 64 字节主密钥。"""
    return hashlib.scrypt(
        material,
        salt=_KDF_SALT,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """用 HMAC-SHA256 生成密钥流（counter mode 构造）。"""
    mac_key = key[:32]
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(mac_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


class SecretBox:
    """加密/解密与掩码展示。"""

    def __init__(self, key_path: Path | str | None = None, *, material: bytes | None = None):
        if material is None:
            if key_path is None:
                from ..config import get_settings

                settings = get_settings()
                key_path = settings.resolve_path(settings.data_dir) / SECRET_FILE
            self.key_path = Path(key_path)
            material = self._load_material()
        else:
            self.key_path = Path(key_path) if key_path else None
        self._master = derive_key(material)

    # -- 密钥来源 ---------------------------------------------------------
    def _load_material(self) -> bytes:
        env_value = os.environ.get(ENV_SECRET, "").strip()
        if env_value:
            return env_value.encode("utf-8")
        assert self.key_path is not None
        if self.key_path.is_file():
            data = self.key_path.read_bytes().strip()
            if not data:
                raise SecretError(
                    f"密钥文件为空：{self.key_path}。删除该文件可重新生成，但已保存的 Key 将无法解密。"
                )
            return data
        return self._generate_persisted()

    def _generate_persisted(self) -> bytes:
        assert self.key_path is not None
        material = hashlib.sha256(secrets.token_bytes(32) + os.urandom(16)).digest()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(base64.b64encode(material))
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:  # pragma: no cover - Windows 上多为无效
            pass
        return material

    # -- 加解密 -----------------------------------------------------------
    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            raise SecretError("不能加密 None")
        raw = plaintext.encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        stream = _keystream(self._master, nonce, len(raw))
        ciphertext = _xor(raw, stream)
        tag = hmac.new(self._master[32:], nonce + ciphertext, hashlib.sha256).digest()
        return _VERSION_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")

    def decrypt(self, token: str) -> str:
        if not token:
            raise SecretError("密文为空")
        if not token.startswith(_VERSION_PREFIX):
            raise SecretError("密文版本不支持，请重新填写 API Key")
        try:
            blob = base64.urlsafe_b64decode(token[len(_VERSION_PREFIX) :].encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise SecretError(f"密文格式损坏：{exc}") from exc
        if len(blob) <= _NONCE_BYTES + 32:
            raise SecretError("密文长度异常")
        nonce = blob[:_NONCE_BYTES]
        ciphertext = blob[_NONCE_BYTES:-32]
        tag = blob[-32:]
        expected = hmac.new(self._master[32:], nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise SecretError(
                "无法解密已保存的 API Key：密钥文件可能被替换，或密文被篡改。请在设置中重新填写。"
            )
        stream = _keystream(self._master, nonce, len(ciphertext))
        return _xor(ciphertext, stream).decode("utf-8")

    # -- 展示 -------------------------------------------------------------
    @staticmethod
    def mask(value: str | None) -> str:
        """返回可安全展示的掩码，绝不返回完整 Key。"""
        if not value:
            return ""
        text = value.strip()
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:3]}****{text[-4:]}"

    @staticmethod
    def looks_like_key(value: str) -> bool:
        """粗略校验，只拦明显错误（如把 URL 当成 Key 填进来）。"""
        text = (value or "").strip()
        if len(text) < 8:
            return False
        if text.startswith(("http://", "https://")):
            return False
        return " " not in text


__all__ = ["ENV_SECRET", "SECRET_FILE", "SecretBox", "SecretError", "derive_key"]
