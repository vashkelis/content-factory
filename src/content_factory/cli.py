"""Typer CLI for content-factory."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from content_factory.models import ARTIFACT_NAMES, Brief, RunMeta
from content_factory.storage import (
    artifact_path,
    create_run_dir,
    find_run_dir,
    list_runs,
    read_json,
    write_json,
)

app = typer.Typer(
    name="cf",
    help="content-factory: reproducible content-writing pipeline.",
    add_completion=False,
)
console = Console()

DEFAULT_RUNS_DIR = "runs"


# ── generate ─────────────────────────────────────────────────────────────────

@app.command()
def generate(
    brief_path: str = typer.Argument(..., help="Path to a YAML brief file."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
) -> None:
    """Read a YAML brief, create a run folder with placeholder artifacts."""
    path = Path(brief_path)
    if not path.exists():
        rprint(f"[red]Error:[/red] Brief file not found: {path}")
        raise typer.Exit(1)

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        brief = Brief.model_validate(raw)
    except Exception as exc:
        rprint(f"[red]Error:[/red] Invalid brief: {exc}")
        raise typer.Exit(1)

    paths = create_run_dir(output, brief.topic)

    # Write brief.json
    write_json(paths.brief_json, brief.model_dump())

    # Write meta.json
    meta = RunMeta(
        run_id=paths.run_id,
        topic=brief.topic,
        language=brief.language,
    )
    write_json(paths.meta_json, meta.model_dump())

    # Write placeholder core.json
    write_json(paths.core_json, {})

    # Write placeholder markdown artifacts
    for md_path in (paths.blog_md, paths.linkedin_md, paths.x_md):
        md_path.write_text("(pending)\n", encoding="utf-8")

    rprint(f"[green]Run created:[/green] {paths.run_id}")
    rprint(f"  [dim]{paths.run_dir}[/dim]")


# ── list ─────────────────────────────────────────────────────────────────────

@app.command(name="list")
def list_cmd(
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
    n: int = typer.Option(20, "--n", "-n", help="Number of recent runs to show."),
) -> None:
    """List recent run folders."""
    runs = list_runs(output, limit=n)
    if not runs:
        rprint("[dim]No runs found.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Recent Runs", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Run ID")
    for i, name in enumerate(runs, 1):
        table.add_row(str(i), name)
    console.print(table)


# ── show ─────────────────────────────────────────────────────────────────────

@app.command()
def show(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
    artifact: str = typer.Option("meta", "-a", "--artifact", help=f"Artifact to display: {', '.join(ARTIFACT_NAMES)}"),
) -> None:
    """Print an artifact from a run to stdout."""
    run_dir = find_run_dir(output, run_id)
    if run_dir is None:
        rprint(f"[red]Error:[/red] Run not found: {run_id}")
        raise typer.Exit(1)

    try:
        ap = artifact_path(run_dir, artifact)
    except ValueError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not ap.exists():
        rprint(f"[red]Error:[/red] Artifact not found: {ap}")
        raise typer.Exit(1)

    content = ap.read_text(encoding="utf-8")
    if ap.suffix == ".json":
        # Pretty-print JSON
        try:
            data = json.loads(content)
            rprint(json.dumps(data, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            console.print(content)
    else:
        console.print(content)


# ── core ─────────────────────────────────────────────────────────────────────

@app.command()
def core(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
    model: str = typer.Option("gpt-4o-mini", "--model", "-m", help="OpenAI model to use."),
) -> None:
    """Generate ContentCore for a run using LLM."""
    run_dir = find_run_dir(output, run_id)
    if run_dir is None:
        rprint(f"[red]Error:[/red] Run not found: {run_id}")
        raise typer.Exit(1)

    brief_path = run_dir / "brief.json"
    if not brief_path.exists():
        rprint(f"[red]Error:[/red] brief.json not found in {run_dir}")
        raise typer.Exit(1)

    brief = Brief.model_validate(read_json(brief_path))

    # Load meta
    meta_path = run_dir / "meta.json"
    meta = RunMeta.model_validate(read_json(meta_path))

    # Try to create provider
    try:
        from content_factory.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(model=model)
    except EnvironmentError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    rprint(f"[blue]Generating ContentCore[/blue] for [bold]{brief.topic}[/bold] with model [dim]{model}[/dim]...")

    try:
        from content_factory.graph import run_core_pipeline

        core_result, error = run_core_pipeline(brief=brief, provider=provider)
    except Exception as exc:
        error = str(exc)
        core_result = None

    now = datetime.utcnow().isoformat()

    if error:
        meta.status = "error"
        meta.error_message = error
        meta.updated_at = now
        write_json(meta_path, meta.model_dump())
        rprint(f"[red]Error during core generation:[/red] {error}")
        raise typer.Exit(1)

    # Write core.json
    core_path = run_dir / "core.json"
    write_json(core_path, core_result.model_dump())  # type: ignore[union-attr]

    # Update meta
    meta.status = "core_generated"
    meta.model = model
    meta.updated_at = now
    meta.error_message = None
    write_json(meta_path, meta.model_dump())

    rprint(f"[green]ContentCore written:[/green] {core_path}")


# ── patch (stub) ─────────────────────────────────────────────────────────────

@app.command()
def patch(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    platform: str = typer.Option(..., "--platform", "-p", help="Platform: blog, linkedin, or x."),
    message: str = typer.Option(..., "-m", "--message", help="Patch directive."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
) -> None:
    """Append a patch directive for a platform (stub -- application not yet implemented)."""
    run_dir = find_run_dir(output, run_id)
    if run_dir is None:
        rprint(f"[red]Error:[/red] Run not found: {run_id}")
        raise typer.Exit(1)

    if platform not in ("blog", "linkedin", "x"):
        rprint(f"[red]Error:[/red] Invalid platform '{platform}'. Choose: blog, linkedin, x")
        raise typer.Exit(1)

    patch_file = run_dir / f"patches_{platform}.jsonl"
    entry = json.dumps(
        {"timestamp": datetime.utcnow().isoformat(), "directive": message},
        ensure_ascii=False,
    )
    with open(patch_file, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

    rprint(f"[green]Patch appended:[/green] {patch_file}")
    rprint(f"  [dim]{message}[/dim]")
    rprint("[yellow]Note:[/yellow] Full patch application is not yet implemented.")


if __name__ == "__main__":
    app()
