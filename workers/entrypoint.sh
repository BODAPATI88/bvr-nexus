#!/bin/bash
# BVR Worker Entrypoint — Starts ALL workers, not just review
set -e

echo "🚀 Starting BVR Worker Pool..."

# Start all three workers in background
python -m workers.review_worker &
REVIEW_PID=$!
echo "  ✅ Review Worker (PID: $REVIEW_PID)"

python -m workers.research_worker &
RESEARCH_PID=$!
echo "  ✅ Research Worker (PID: $RESEARCH_PID)"

python -m workers.achieve_worker &
ACHIEVE_PID=$!
echo "  ✅ Achieve Worker (PID: $ACHIEVE_PID)"

# Health check endpoint
python -m workers.health_server &
HEALTH_PID=$!
echo "  ✅ Health Server (PID: $HEALTH_PID)"

# Graceful shutdown handler
cleanup() {
    echo ""
    echo "🛑 Shutting down workers gracefully..."
    kill -TERM $REVIEW_PID $RESEARCH_PID $ACHIEVE_PID $HEALTH_PID 2>/dev/null || true
    wait $REVIEW_PID $RESEARCH_PID $ACHIEVE_PID $HEALTH_PID 2>/dev/null || true
    echo "✅ All workers stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT

echo ""
echo "👷 All workers running. Waiting for events..."
echo "   Press Ctrl+C or send SIGTERM to stop."

# Wait for any child to exit
wait -n

# If we get here, a worker crashed
echo "❌ A worker exited unexpectedly!"
cleanup
