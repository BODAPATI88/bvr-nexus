import os
import shutil
from typing import Dict, Any
from dulwich import porcelain

async def execute(config: dict, inputs: dict) -> Dict[str, Any]:
    """Execute GitHub operations."""
    action = inputs["action"]

    if action == "clone":
        repo_url = inputs["repo_url"]
        branch = inputs.get("branch", "main")
        target_dir = f"/tmp/repos/{os.path.basename(repo_url)}"

        # Remove stale clone if present so re-runs work cleanly
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs("/tmp/repos", exist_ok=True)

        porcelain.clone(repo_url, target_dir, branch=branch.encode(), depth=1)

        # List files
        files = []
        for root, dirs, filenames in os.walk(target_dir):
            # Skip .git directory
            dirs[:] = [d for d in dirs if d != ".git"]
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
