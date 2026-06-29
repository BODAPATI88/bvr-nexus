"""
BVR Achieve Worker — Optimizes resumes for ATS screening.
"""

import asyncio
import json
from typing import Dict, Any
from workers.base import BaseWorker
from bvr_sdk import (
    EventEnvelope, emit_event, trace_span,
    ai_gateway_call, upload_artifact
)

class ResumeOptimizerWorker(BaseWorker):
    worker_id = "resume-optimizer"
    capabilities = ["achieve.resume-optimization", "optimize_ats"]
    version = "2.0.0"

    @trace_span("achieve.optimize_resume")
    async def handle(self, event: EventEnvelope) -> Dict[str, Any]:
        resume_content = event.payload.get("resume_content", "")
        target_role = event.payload.get("target_role", "Software Engineer")

        print(f"[ACHIEVE] Optimizing resume for: {target_role}")

        # Step 1: Analyze current resume via Capability Matcher
        from bvr_sdk import get_matcher
        matcher = get_matcher()

        # Resolve "document_analysis" capability
        analysis_provider = matcher.resolve("document_analysis", workflow_id="bvr.achieve.resume-optimization")
        analysis_config = matcher.get_provider_config(analysis_provider.id)

        analysis_prompt = f"""
        Analyze this resume for ATS optimization:

        Target Role: {target_role}

        Resume:
        {resume_content[:2000]}...

        Evaluate:
        1. Keyword match for target role
        2. Formatting for ATS parsing
        3. Missing skills or certifications
        4. Action verbs and quantifiable achievements
        5. Overall ATS score (0-100)

        Provide specific improvement suggestions.
        """

        analysis = await ai_gateway_call(
            capability="analysis",
            prompt=analysis_prompt,
            model_preference="claude"
        )

        initial_score = self._extract_score(analysis["text"])

        # Step 2: Generate optimized resume
        optimize_prompt = f"""
        Based on the analysis above, rewrite this resume to maximize ATS score for:

        Target Role: {target_role}

        Original Resume:
        {resume_content[:2000]}...

        Improvements needed:
        {analysis["text"]}

        Produce an optimized resume with:
        - Improved keyword density
        - Better formatting for ATS
        - Stronger action verbs
        - Quantified achievements
        - Professional summary

        Also provide the new estimated ATS score.
        """

        optimized = await ai_gateway_call(
            capability="creative_writing",
            prompt=optimize_prompt,
            model_preference="gpt"
        )

        optimized_score = self._extract_score(optimized["text"])
        score_delta = optimized_score - initial_score

        # Step 3: Generate artifact
        report = f"""# Resume Optimization Report

**Target Role:** {target_role}  
**Execution ID:** {event.correlation_id}

## Original Analysis
{analysis["text"]}

## Optimized Resume
{optimized["text"]}

## Score Improvement
**Before:** {initial_score}/100  
**After:** {optimized_score}/100  
**Delta:** +{score_delta} points ✅

## Metadata
- Model: {optimized.get("model_used", "unknown")}
- Cost: ${optimized.get("cost_usd", 0):.4f}
"""

        artifact_url = await upload_artifact(
            data=report.encode(),
            path=f"resumes/{event.correlation_id}/optimized.md",
            content_type="text/markdown"
        )

        return {
            "initial_score": initial_score,
            "optimized_score": optimized_score,
            "score_delta": score_delta,
            "artifact_url": artifact_url,
            "model_used": optimized.get("model_used"),
            "cost_usd": optimized.get("cost_usd"),
            "status": "completed"
        }

    def _extract_score(self, text: str) -> int:
        import re
        match = re.search(r'(?:score|rating)[:\s]+(\d{2,3})', text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 70  # Default

if __name__ == "__main__":
    worker = ResumeOptimizerWorker()
    asyncio.run(worker.start())
