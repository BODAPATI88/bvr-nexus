"""
Health server for BVR workers — exposes /health endpoint for Docker health checks.
"""

from fastapi import FastAPI
import uvicorn
import psutil
import os

app = FastAPI()

@app.get("/health")
async def health():
    """Return worker pool health status."""
    # Check if worker processes are running
    worker_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'workers.review_worker' in cmdline or 'workers.research_worker' in cmdline or 'workers.achieve_worker' in cmdline:
                worker_processes.append({
                    "pid": proc.info['pid'],
                    "type": cmdline.split('.')[-1].replace('_worker', '')
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Check Redis connectivity
    redis_ok = False
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        redis_ok = r.ping()
        r.close()
    except Exception:
        pass

    status = "healthy" if len(worker_processes) >= 3 and redis_ok else "degraded"

    return {
        "status": status,
        "workers_running": len(worker_processes),
        "workers_expected": 3,
        "redis_connected": redis_ok,
        "worker_details": worker_processes,
        "memory_percent": psutil.virtual_memory().percent,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
