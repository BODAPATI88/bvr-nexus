"""
Artifact storage — MinIO operations.
"""

import os
import io
from typing import Optional, List
from minio import Minio

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "bvradmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "bvrsecret123")

def get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT.replace("http://", "").replace("https://", ""),
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_ENDPOINT.startswith("https")
    )

async def upload_artifact(
    data: bytes,
    path: str,
    bucket: str = "bvr-artifacts",
    content_type: str = "application/octet-stream"
) -> str:
    """Upload artifact to MinIO. Returns URL."""
    client = get_minio_client()

    # Ensure bucket exists
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    client.put_object(
        bucket,
        path,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type
    )

    return f"{MINIO_ENDPOINT}/{bucket}/{path}"

async def download_artifact(path: str, bucket: str = "bvr-artifacts") -> bytes:
    """Download artifact from MinIO."""
    client = get_minio_client()
    response = client.get_object(bucket, path)
    return response.read()

async def list_artifacts(prefix: str, bucket: str = "bvr-artifacts") -> List[str]:
    """List artifacts by prefix."""
    client = get_minio_client()
    objects = client.list_objects(bucket, prefix=prefix, recursive=True)
    return [obj.object_name for obj in objects]
