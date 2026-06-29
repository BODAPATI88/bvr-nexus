from setuptools import setup, find_packages

setup(
    name="bvr-sdk",
    version="2.0.0",
    description="BVR Nexus SDK — Standardized interface for all BVR workers",
    author="BVR Group",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.7.0",
        "redis>=5.0.0",
        "aioredis>=2.0.0",
        "httpx>=0.27.0",
        "minio>=7.2.0",
        "tenacity>=8.3.0",
        "opentelemetry-api>=1.25.0",
        "opentelemetry-sdk>=1.25.0",
        "opentelemetry-exporter-otlp>=1.25.0",
    ],
    python_requires=">=3.10",
)
