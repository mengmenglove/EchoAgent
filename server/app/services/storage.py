"""文件存储抽象：开发用本地目录，上线换 S3 协议的对象存储（MinIO / 阿里云 OSS / AWS S3）。

Key 规则：users/{user_id}/jobs/{job_id}/final.mp3 —— 按用户隔离，便于清理和统计。
"""

import asyncio
from pathlib import Path
from typing import Protocol

from app.config import Settings


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    def local_path(self, key: str) -> Path | None:
        """本地存储返回文件路径（用 FileResponse 直接发送）；对象存储返回 None。"""
        ...

    async def presigned_url(self, key: str, expires: int = 3600, download_name: str | None = None) -> str: ...


def _safe_key(key: str) -> str:
    # key 全部由服务端生成，这里再防一手路径穿越
    if key.startswith("/") or ".." in Path(key).parts:
        raise ValueError(f"非法的存储 key：{key}")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        # 文件 IO 是阻塞调用，放到线程里执行，避免卡住事件循环
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)

    async def delete_prefix(self, prefix: str) -> None:
        import shutil

        path = self._path(prefix)
        if path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path, True)
        elif path.exists():
            await asyncio.to_thread(path.unlink)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

    async def presigned_url(self, key: str, expires: int = 3600, download_name: str | None = None) -> str:
        raise NotImplementedError("本地存储通过 API 直接发送文件，不需要预签名 URL")


class S3Storage:
    """S3 协议存储。boto3 是同步库，所有调用都放进线程池执行。"""

    def __init__(self, bucket: str, endpoint_url: str | None, region: str | None):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=_safe_key(key),
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=_safe_key(key))
        return await asyncio.to_thread(obj["Body"].read)

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    async def delete_prefix(self, prefix: str) -> None:
        resp = await asyncio.to_thread(self.client.list_objects_v2, Bucket=self.bucket, Prefix=_safe_key(prefix))
        keys = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        if keys:
            await asyncio.to_thread(self.client.delete_objects, Bucket=self.bucket, Delete={"Objects": keys})

    def local_path(self, key: str) -> Path | None:
        return None

    async def presigned_url(self, key: str, expires: int = 3600, download_name: str | None = None) -> str:
        params = {"Bucket": self.bucket, "Key": _safe_key(key)}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        return await asyncio.to_thread(
            self.client.generate_presigned_url, "get_object", Params=params, ExpiresIn=expires
        )


def make_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings.s3_bucket, settings.s3_endpoint_url, settings.s3_region)
    return LocalStorage(settings.storage_dir)


def job_prefix(user_id, job_id) -> str:
    return f"users/{user_id}/jobs/{job_id}"


def voice_key(user_id, voice_id) -> str:
    return f"users/{user_id}/voices/{voice_id}.wav"


def tts_cache_key(hash_: str) -> str:
    return f"tts-cache/{hash_[:2]}/{hash_}.wav"
