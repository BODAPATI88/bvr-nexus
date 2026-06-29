import subprocess
import os
from typing import Dict, Any

async def execute(config: dict, inputs: dict) -> Dict[str, Any]:
    """Execute GitHub operations."""
    action = inputs["action"]

    if action == "clone":
        repo_url = inputs["repo_url"]
        branch = inputs.get("branch", "main")
        target_dir = f"/tmp/repos/{os.path.basename(repo_url)}"

        subprocess.run(
            ["git", "clone", "-b", branch, "--depth", "1", repo_url, target_dir],
            check=True,
            capture_output=True
        )

        # List files
        files = []
        for root, dirs, filenames in os.walk(target_dir):
            for f in filenames:
                files.append(os.path.relpath(os.path.join(root, f), target_dir))

        return {
            "result": "cloned",
            "url": repo_url,
            "directory": target_dir,
            "files": files[:100],  # Limit for brevity
        }

    elif action == "create_pr":
        # In production: use PyGithub
        return {
            "result": "pr_created",
            "url": f"{inputs['repo_url']}/pull/1",
        }

    return {"result": "unknown_action"}
