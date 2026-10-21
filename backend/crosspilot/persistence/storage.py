"""对象存储抽象（阶段 E6）。

当前只有本地实现：文件落在 ``data/uploads``，数据库只存相对 ``storage_key``。
接口保留 ``put/get/delete/presign``，生产换 S3 只需替换实现，不动业务代码。

安全边界：
- ``key`` 只允许相对路径，拒绝 ``..`` 与绝对路径，避免目录穿越；
- 本地实现不提供公网 URL，``presign`` 返回 ``None``，调用方必须走鉴权接口读取。
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(RuntimeError):
    """存储读写失败（消息可直接展示）。"""


@runtime_checkable
class ObjectStorage(Protocol):
    name: str

    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> bool: ...

    def exists(self, key: str) -> bool: ...

    def presign(self, key: str, expires_seconds: int = 600) -> str | None: ...


class LocalStorage:
    name = "local"

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- 路径安全 ----------------------------------------------------------
    def _resolve(self, key: str) -> Path:
        text = (key or "").replace("\\", "/").strip("/")
        if not text or ".." in text.split("/"):
            raise StorageError(f"非法存储 key：{key!r}")
        path = (self.root / text).resolve()
        if self.root not in path.parents and path != self.root:
            raise StorageError(f"存储 key 越界：{key!r}")
        return path

    @staticmethod
    def sanitize_name(name: str) -> str:
        """把用户文件名压成安全片段，保留扩展名。"""
        base = Path(name or "upload").name
        stem = _SAFE_SEGMENT.sub("_", Path(base).stem)[:60] or "upload"
        suffix = _SAFE_SEGMENT.sub("", Path(base).suffix)[:12]
        return stem + suffix

    # -- 接口 --------------------------------------------------------------
    def put(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"写入文件失败：{exc}") from exc
        return key.replace("\\", "/")

    def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"文件不存在：{key}") from exc
        except OSError as exc:
            raise StorageError(f"读取文件失败：{exc}") from exc

    def delete(self, key: str) -> bool:
        path = self._resolve(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def presign(self, key: str, expires_seconds: int = 600) -> str | None:
        # 本地实现没有可分享的 URL；读取必须走鉴权 API
        return None

    def clear(self) -> None:  # pragma: no cover - 测试/运维用
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


class SupabaseStorage:
    """Supabase Storage 实现（S3 兼容的 REST 接口，不引第三方 SDK）。

    只用标准库 ``urllib`` 调用 Storage REST API，避免为了一个上传功能
    再背 ``supabase-py`` 依赖。部署时用 service_role key 以绕过 RLS。

    配置（环境变量）：
    - ``CROSSPILOT_STORAGE_BACKEND=supabase``
    - ``CROSSPILOT_SUPABASE_URL``
    - ``CROSSPILOT_SUPABASE_SERVICE_KEY``
    - ``CROSSPILOT_SUPABASE_BUCKET``（默认 crosspilot）

    安全边界：``key`` 仍走与本地实现相同的路径校验，拒绝 ``..`` 与绝对路径。
    """

    name = "supabase"

    def __init__(self, url: str, service_key: str, bucket: str = "crosspilot"):
        if not url or not service_key:
            raise StorageError(
                "Supabase Storage 需要 CROSSPILOT_SUPABASE_URL 与 "
                "CROSSPILOT_SUPABASE_SERVICE_KEY"
            )
        self.base_url = url.rstrip("/")
        self.service_key = service_key
        self.bucket = bucket or "crosspilot"

    # -- 路径安全 ----------------------------------------------------------
    @staticmethod
    def _check_key(key: str) -> str:
        text = (key or "").replace("\\", "/").strip("/")
        if not text or ".." in text.split("/") or ":" in text.split("/")[0]:
            raise StorageError(f"非法存储 key：{key!r}")
        return text

    def _request(self, method: str, path: str, *, data: bytes | None = None) -> bytes:
        import json
        import urllib.error
        import urllib.request

        url = f"{self.base_url}/storage/v1/{path}"
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.service_key}")
        request.add_header("apikey", self.service_key)
        if data is not None:
            request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = json.loads(exc.read().decode("utf-8")).get("message", "")
            except Exception:  # noqa: BLE001 - 解析失败就用状态码
                pass
            raise StorageError(
                f"Supabase Storage {method} 失败（HTTP {exc.code}）：{body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise StorageError(f"无法连接 Supabase Storage：{exc.reason}") from exc

    # -- 接口 --------------------------------------------------------------
    def put(self, key: str, data: bytes) -> str:
        safe = self._check_key(key)
        self._request(
            "POST",
            f"object/{self.bucket}/{safe}",
            data=data,
        )
        return safe

    def get(self, key: str) -> bytes:
        safe = self._check_key(key)
        return self._request("GET", f"object/{self.bucket}/{safe}")

    def delete(self, key: str) -> bool:
        safe = self._check_key(key)
        try:
            self._request("DELETE", f"object/{self.bucket}/{safe}")
            return True
        except StorageError:
            return False

    def exists(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except StorageError:
            return False

    def presign(self, key: str, expires_seconds: int = 600) -> str | None:
        """返回签名 URL（前端可直接下载）；失败时返回 None，调用方回落鉴权接口。"""
        import json

        safe = self._check_key(key)
        try:
            payload = json.dumps({"expiresIn": int(expires_seconds)}).encode("utf-8")
            raw = self._request(
                "POST", f"object/sign/{self.bucket}/{safe}", data=payload
            )
            signed = json.loads(raw.decode("utf-8")).get("signedURL")
            if not signed:
                return None
            return f"{self.base_url}/storage/v1{signed}"
        except (StorageError, ValueError):
            return None


def build_storage(settings) -> ObjectStorage:
    """按配置选择存储后端；未知后端明确报错，不静默回落到本地。"""
    backend = (getattr(settings, "storage_backend", "local") or "local").lower()
    if backend == "local":
        return LocalStorage(settings.uploads_dir)
    if backend == "supabase":
        return SupabaseStorage(
            getattr(settings, "supabase_url", ""),
            getattr(settings, "supabase_service_key", ""),
            getattr(settings, "supabase_bucket", "crosspilot"),
        )
    raise StorageError(f"未知的存储后端 {backend!r}，可选：local / supabase")


__all__ = [
    "LocalStorage",
    "ObjectStorage",
    "StorageError",
    "SupabaseStorage",
    "build_storage",
]
