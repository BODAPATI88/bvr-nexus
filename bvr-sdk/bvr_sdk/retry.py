"""
Retry, timeout, and circuit breaker utilities.
Uses tenacity for retry logic.
"""

import os
import functools
from typing import Callable, Any
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)
import logging

logger = logging.getLogger("bvr.sdk.retry")

DEFAULT_MAX_RETRIES = int(os.getenv("BVR_MAX_RETRIES", "3"))
DEFAULT_TIMEOUT = int(os.getenv("BVR_DEFAULT_TIMEOUT", "30"))

def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    min_wait: int = 1,
    max_wait: int = 60,
    exceptions: tuple = (Exception,)
):
    """Decorator to add retry logic to any function."""
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=min_wait, max=max_wait),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True
        )
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=min_wait, max=max_wait),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True
        )
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

def with_timeout(seconds: int = DEFAULT_TIMEOUT):
    """Decorator to add timeout to async functions."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
        return wrapper
    return decorator

def with_circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60
):
    """Simple circuit breaker decorator."""
    state = {"failures": 0, "last_failure": None, "open": False}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if state["open"]:
                if (asyncio.get_event_loop().time() - state["last_failure"]) < recovery_timeout:
                    raise Exception("Circuit breaker is OPEN")
                state["open"] = False
                state["failures"] = 0

            try:
                result = await func(*args, **kwargs)
                state["failures"] = 0
                return result
            except Exception as e:
                state["failures"] += 1
                state["last_failure"] = asyncio.get_event_loop().time()
                if state["failures"] >= failure_threshold:
                    state["open"] = True
                raise e

        return async_wrapper
    return decorator

import asyncio
