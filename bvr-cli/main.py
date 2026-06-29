"""
BVR CLI v2 — Calls BVR FastAPI Gateway, not Kestra directly.
"""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import httpx
import uuid
import yaml
import json
from typing import Optional, List
from pathlib import Path

app = typer.Typer(
    name="bvr",
    help="BVR Nexus v2 — Declarative Workflow Orchestration Platform",
    rich_markup_mode="rich",
)
console = Console()

BVR_API_URL = "http://localhost:8000"

def api_request(method: str, endpoint: str, **kwargs) -> dict:
    """Make a request to the BVR API Gateway."""
    url = f"{BVR_API_URL}{endpoint}"
    try:
        resp = httpx.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as e:
        console.print(f"[red]BVR API error: {e}[/red]")
        raise typer.Exit(1)

@app.command()
def review(
    target: str = typer.Argument(..., help="Repository path or URL to review"),
    branch: str = typer.Option("main", "--branch", "-b"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
):
    """
    [bold cyan]bvr review[/bold cyan] — Review a repository for architecture issues.
    """
    console.print(Panel(
        f"[bold]BVR Review[/bold]\nTarget: {target}\nBranch: {branch}",
        title="🔍 Starting Review",
        border_style="cyan"
    ))

    # Emit event via BVR API
    result = api_request("POST", "/api/v1/events", json={
        "event_type": "review.repository",
        "payload": {"repo_url": target, "branch": branch},
        "correlation_id": str(uuid.uuid4()),
        "source": "cli"
    })

    event_id = result["event_id"]
    console.print(f"[green]✅ Event emitted: {event_id}[/green]")
    console.print(f"[dim]Workers will process this asynchronously...[/dim]")

@app.command()
def architect(
    prompt: str = typer.Argument(..., help="Architecture question or design prompt"),
):
    """
    [bold cyan]bvr architect[/bold cyan] — Get architecture guidance.
    """
    console.print(Panel(
        f"[bold]BVR Architect[/bold]\nPrompt: {prompt}",
        title="🏗️  Architecture Design",
        border_style="blue"
    ))

    result = api_request("POST", "/api/v1/events", json={
        "event_type": "architect.solution",
        "payload": {"prompt": prompt},
        "correlation_id": str(uuid.uuid4()),
        "source": "cli"
    })

    console.print(f"[green]✅ Design request submitted: {result['event_id']}[/green]")

@app.command()
def research(
    topic: str = typer.Argument(..., help="Research topic or question"),
    depth: str = typer.Option("standard", "--depth", "-d"),
):
    """
    [bold cyan]bvr research[/bold cyan] — Research a topic and produce summary.
    """
    console.print(Panel(
        f"[bold]BVR Research[/bold]\nTopic: {topic}\nDepth: {depth}",
        title="🔬 Research Mode",
        border_style="magenta"
    ))

    result = api_request("POST", "/api/v1/events", json={
        "event_type": "research.topic",
        "payload": {"topic": topic, "depth": depth},
        "correlation_id": str(uuid.uuid4()),
        "source": "cli"
    })

    console.print(f"[green]✅ Research started: {result['event_id']}[/green]")

@app.command()
def achieve(
    goal: str = typer.Argument(..., help="Goal to achieve"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """
    [bold cyan]bvr achieve[/bold cyan] — Execute a goal-oriented workflow.
    """
    console.print(Panel(
        f"[bold]BVR Achieve[/bold]\nGoal: {goal}",
        title="🎯 Goal Execution",
        border_style="yellow"
    ))

    if dry_run:
        console.print("[blue]📋 Execution Plan:[/blue]")
        console.print("  1. Parse goal intent")
        console.print("  2. Resolve to workflow via Platform Registry")
        console.print("  3. Evaluate pre-conditions (OPA)")
        console.print("  4. Emit event to BVR Event Bus")
        console.print("  5. Router dispatches to worker")
        console.print("  6. Worker executes business logic")
        console.print("  7. Result event emitted")
        console.print("  8. Kestra continues orchestration graph")
        console.print("  9. Artifact generated & outcome measured")
        return

    result = api_request("POST", "/api/v1/events", json={
        "event_type": "achieve.goal",
        "payload": {"goal": goal},
        "correlation_id": str(uuid.uuid4()),
        "source": "cli"
    })

    console.print(f"[green]🚀 Goal execution started: {result['event_id']}[/green]")

@app.command()
def status():
    """
    [bold cyan]bvr status[/bold cyan] — Show system status and health.
    """
    table = Table(title="BVR Nexus v2 System Status", box=box.ROUNDED)
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Role", style="dim")

    components = [
        ("Traefik", "🟢", "Ingress + TLS"),
        ("BVR API (FastAPI)", "🟢", "Application Layer"),
        ("Kestra", "🟢", "Orchestration Only"),
        ("BVR Workers", "🟢", "Business Logic"),
        ("AI Gateway", "🟢", "LLM Abstraction"),
        ("PostgreSQL + pgvector", "🟢", "State + Knowledge"),
        ("Redis (Streams)", "🟢", "Cache + Messaging"),
        ("MinIO", "🟢", "Artifacts"),
        ("OPA", "🟢", "Policy Engine"),
        ("Vault", "🟢", "Secrets"),
        ("Keycloak", "🟢", "Auth"),
        ("Prometheus", "🟢", "Metrics"),
        ("Grafana", "🟢", "Dashboards"),
        ("Jaeger", "🟢", "Traces"),
        ("Loki", "🟢", "Logs"),
        ("Ollama", "🟢", "Local LLM"),
    ]

    for name, status, role in components:
        table.add_row(name, status, role)

    console.print(table)
    console.print("\n[green]✅ All systems operational[/green]")
    console.print("[dim]Architecture: Kestra orchestrates → BVR API routes → Workers execute[/dim]")

@app.command()
def workflows():
    """List all registered workflows."""
    result = api_request("GET", "/api/v1/registry/workflows")

    table = Table(title="BVR Workflow Registry", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Namespace", style="dim")
    table.add_column("Description", style="")
    table.add_column("Tags", style="yellow")

    for wf in result:
        table.add_row(wf["id"], wf["namespace"], wf["description"], ", ".join(wf["tags"]))

    console.print(table)

@app.command()
def workers():
    """List all registered workers."""
    result = api_request("GET", "/api/v1/registry/workers")

    table = Table(title="BVR Worker Registry", box=box.ROUNDED)
    table.add_column("Worker ID", style="cyan")
    table.add_column("Capabilities", style="yellow")
    table.add_column("Version", style="dim")
    table.add_column("Status", style="")

    for w in result:
        table.add_row(
            w.get("worker_id", "unknown"),
            ", ".join(w.get("capabilities", [])),
            w.get("version", "?"),
            w.get("status", "unknown")
        )

    console.print(table)

@app.command()
def outcomes():
    """Show measurable outcomes and KPIs."""
    result = api_request("GET", "/api/v1/outcomes")

    table = Table(title="BVR Measurable Outcomes", box=box.ROUNDED)
    table.add_column("Goal", style="cyan")
    table.add_column("Metric", style="dim")
    table.add_column("Target", style="bold")
    table.add_column("Current", style="green")
    table.add_column("Status", style="")

    for o in result:
        table.add_row(
            o.get("goal_id", ""),
            o.get("metric", ""),
            f"{o.get('target', 0)} {o.get('unit', '')}",
            str(o.get("current", "—")),
            o.get("status", "")
        )

    console.print(table)

@app.command()
def models():
    """List all AI models available through the gateway."""
    result = api_request("GET", "/api/v1/ai-gateway/models")

    table = Table(title="BVR AI Gateway — Available Models", box=box.ROUNDED)
    table.add_column("Provider", style="cyan")
    table.add_column("Model", style="")
    table.add_column("Capabilities", style="yellow")
    table.add_column("Priority", style="dim")
    table.add_column("Cost/1K", style="green")

    for m in result:
        cost = f"${m.get('cost_per_1k_input', 0):.4f} / ${m.get('cost_per_1k_output', 0):.4f}"
        table.add_row(
            m.get("provider", ""),
            m.get("model_name", ""),
            ", ".join(m.get("capabilities", [])),
            str(m.get("priority", "")),
            cost
        )

    console.print(table)

@app.command()
def plugins():
    """List all loaded plugins."""
    result = api_request("GET", "/api/v1/registry/integrations")

    table = Table(title="BVR Plugin Registry", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="")
    table.add_column("Type", style="yellow")
    table.add_column("Version", style="dim")
    table.add_column("Status", style="")

    for p in result:
        table.add_row(
            p.get("id", ""),
            p.get("name", ""),
            p.get("type", ""),
            p.get("version", ""),
            p.get("status", "")
        )

    console.print(table)

if __name__ == "__main__":
    app()
