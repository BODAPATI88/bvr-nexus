"""
BVR Review Worker — Analyzes code repositories for architecture issues.
Uses BVR SDK for all platform operations.
"""

import asyncio
import json
import os
from typing import Dict, Any
from workers.base import BaseWorker
from bvr_sdk import (
    EventEnvelope, emit_event, trace_span,
    ai_gateway_call, upload_artifact, check_policy
)

class ReviewWorker(BaseWorker):
    worker_id = "code-analyzer"
    capabilities = ["review.repository", "analyze_code", "scan_repo"]
    version = "2.0.0"

    @trace_span("review.analyze")
    async def handle(self, event: EventEnvelope) -> Dict[str, Any]:
        repo_url = event.payload["repo_url"]
        branch = event.payload.get("branch", "main")

        print(f"[REVIEW] Analyzing {repo_url} on branch {branch}")

        # Step 1: Clone repo via Capability Matcher
        from bvr_sdk import get_matcher
        matcher = get_matcher()

        # Resolve the "clone_repository" capability to a provider
        provider = matcher.resolve("clone_repository", workflow_id="bvr.review.repository")
        config = matcher.get_provider_config(provider.id)

        # Execute via plugin registry
        registry = self.registry
        result = await registry.execute(provider.id, config, {
            "action": "clone",
            "repo_url": repo_url,
            "branch": branch
        })
        clone_result = result

        repo_path = clone_result["directory"]
        files = clone_result["files"]

        # Step 2: Analyze with LLM via AI Gateway
        analysis_prompt = f"""
        Analyze the architecture of this codebase:

        Repository: {repo_url}
        Files: {len(files)} total
        Sample files: {', '.join(files[:10])}

        Evaluate:
        1. Architecture patterns used
        2. Separation of concerns
        3. Dependency management
        4. Security considerations
        5. Scalability indicators

        Provide a score out of 100 and specific recommendations.
        """

        llm_result = await ai_gateway_call(
            capability="analysis",
            prompt=analysis_prompt,
            model_preference="claude"
        )

        # Step 3: Parse LLM response
        analysis_text = llm_result["text"]

        # Extract score (simple heuristic)
        score = 75  # Default
        if "score" in analysis_text.lower():
            # Try to extract numeric score
            import re
            match = re.search(r'(\d{2,3})\s*/\s*100', analysis_text)
            if match:
                score = int(match.group(1))

        # Step 4: Generate report artifact
        report = f"""# BVR Architecture Review Report

**Repository:** {repo_url}  
**Branch:** {branch}  
**Execution ID:** {event.correlation_id}

## Analysis
{analysis_text}

## Quality Score
**{score}/100**

## Status
{"✅ VALIDATED" if score >= 70 else "⚠️ NEEDS IMPROVEMENT"}

## Metadata
- Files analyzed: {len(files)}
- Model used: {llm_result.get("model_used", "unknown")}
- Cost: ${llm_result.get("cost_usd", 0):.4f}
- Tokens: {llm_result.get("tokens_input", 0)} in / {llm_result.get("tokens_output", 0)} out
"""

        artifact_url = await upload_artifact(
            data=report.encode(),
            path=f"reports/{event.correlation_id}/review.md",
            content_type="text/markdown"
        )

        # Step 5: Notify via Slack
        slack = self.plugin("productivity/slack")
        await slack.execute(
            {"webhook_url": os.getenv("SLACK_WEBHOOK_URL", "")},
            {
                "text": f"Review complete for {repo_url}\nScore: {score}/100",
                "channel": "#bvr-reviews"
            }
        )

        return {
            "score": score,
            "artifact_url": artifact_url,
            "files_analyzed": len(files),
            "model_used": llm_result.get("model_used"),
            "cost_usd": llm_result.get("cost_usd"),
            "status": "completed"
        }

if __name__ == "__main__":
    worker = ReviewWorker()
    asyncio.run(worker.start())
