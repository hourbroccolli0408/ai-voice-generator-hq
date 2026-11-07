from __future__ import annotations

from pathlib import Path

import boto3

from .config import settings


class AudioStorage:
    def __init__(self) -> None:
        self.backend = settings.storage_backend
        self.client = None
        if self.backend == "r2":
            required = {
                "endpoint": settings.r2_endpoint_url,
                "access key": settings.r2_access_key_id,
                "secret": settings.r2_secret_access_key,
                "bucket": settings.r2_bucket,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise RuntimeError(f"Missing R2 configuration: {', '.join(missing)}")
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )

    def store(self, source: Path, key: str) -> str:
        if self.backend == "local":
            return str(source)
        assert self.client is not None and settings.r2_bucket
        self.client.upload_file(
            str(source),
            settings.r2_bucket,
            key,
            ExtraArgs={"ContentType": "audio/wav"},
        )
        source.unlink(missing_ok=True)
        return key

    def url(self, locator: str, download_name: str | None = None) -> str | None:
        if self.backend == "local":
            return None
        if settings.r2_public_url:
            return f"{settings.r2_public_url.rstrip('/')}/{locator}"
        assert self.client is not None and settings.r2_bucket
        params: dict = {"Bucket": settings.r2_bucket, "Key": locator}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=900)
