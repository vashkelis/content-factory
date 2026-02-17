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
from rich.panel import Panel
from rich.table import Table

from content_factory.models import (
    ARTIFACT_NAMES,
    PLATFORMS,
    Brief,
    ContentCore,
    PatchRecord,
    RunMeta,
)
from content_factory.storage import (
    artifact_path,
    create_run_dir,
    find_run_dir,
    list_runs,
    next_patch_number,
    read_json,
    save_patch_record,
    save_run_prompt,
    version_artifact,
    write_json,
    write_text,
)

app = typer.Typer(
    name="cf",
    help="content-factory: reproducible content-writing pipeline.",
    add_completion=False,
)
console = Console()

DEFAULT_RUNS_DIR = "runs"


def _resolve_run(output: str, run_id: str) -> Path:
    """Find a run directory or exit with an error."""
    run_dir = find_run_dir(output, run_id)
    if run_dir is None:
        rprint(f"[red]Error:[/red] Run not found: {run_id}")
        raise typer.Exit(1)
    return run_dir


def _load_meta(run_dir: Path) -> RunMeta:
    meta_path = run_dir / "meta.json"
    return RunMeta.model_validate(read_json(meta_path))


def _save_meta(run_dir: Path, meta: RunMeta) -> None:
    meta.updated_at = datetime.utcnow().isoformat()
    write_json(run_dir / "meta.json", meta.model_dump())


def _make_provider(model: str):
    """Instantiate the OpenAI provider, exiting gracefully if key is missing."""
    try:
        from content_factory.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    except EnvironmentError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


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
    run_dir = _resolve_run(output, run_id)

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
        try:
            data = json.loads(content)
            rprint(json.dumps(data, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            console.print(content)
    else:
        console.print(content)


# ── core (with non-blocking clarification analysis) ──────────────────────────

@app.command()
def core(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
    model: str = typer.Option("gpt-4o-mini", "--model", "-m", help="OpenAI model to use."),
    skip_clarify: bool = typer.Option(False, "--skip-clarify", help="Skip the clarification analysis."),
) -> None:
    """Generate ContentCore for a run using LLM.

    Before generating, the brief is evaluated for completeness.
    If the brief is weak, clarification suggestions are printed AFTER generation,
    and the core is marked as low-context (may contain METRIC_NEEDED placeholders).
    Use 'cf clarify' to add context, then re-run 'cf core' for a richer output.
    """
    run_dir = _resolve_run(output, run_id)

    brief_path_file = run_dir / "brief.json"
    if not brief_path_file.exists():
        rprint(f"[red]Error:[/red] brief.json not found in {run_dir}")
        raise typer.Exit(1)

    brief = Brief.model_validate(read_json(brief_path_file))
    meta = _load_meta(run_dir)
    provider = _make_provider(model)

    # ── Step 1: Clarification analysis (non-blocking) ────────────────────
    clarification_questions: list[str] = []
    needs_clarification = False

    if not skip_clarify:
        rprint(f"[blue]Evaluating brief completeness[/blue] for [bold]{brief.topic}[/bold]...")

        from content_factory.graph import run_clarify_pipeline

        try:
            clarify_result, clarify_error = run_clarify_pipeline(brief=brief, provider=provider)
        except Exception as exc:
            clarify_error = str(exc)
            clarify_result = None

        if clarify_error:
            rprint(f"[yellow]Warning:[/yellow] Clarification analysis failed: {clarify_error}")
            rprint("[dim]Proceeding with core generation anyway.[/dim]")
        elif clarify_result and clarify_result.needs_clarification:
            needs_clarification = True
            clarification_questions = clarify_result.questions
            # Save questions for auditability (but don't stop)
            write_json(
                run_dir / "clarification.json",
                clarify_result.model_dump(),
            )
            rprint("[yellow]Brief has limited context.[/yellow] Generating draft anyway (may use placeholders).")

    # ── Step 2: Core generation (always proceeds) ────────────────────────
    rprint(f"[blue]Generating ContentCore[/blue] for [bold]{brief.topic}[/bold] with model [dim]{model}[/dim]...")

    from content_factory.graph import run_core_pipeline

    try:
        core_result, error = run_core_pipeline(brief=brief, provider=provider)
    except Exception as exc:
        error = str(exc)
        core_result = None

    if error:
        meta.status = "error"
        meta.needs_clarification = needs_clarification
        meta.error_message = error
        meta.model = model
        _save_meta(run_dir, meta)
        rprint(f"[red]Error during core generation:[/red] {error}")
        raise typer.Exit(1)

    # Write core.json
    core_path = run_dir / "core.json"
    write_json(core_path, core_result.model_dump())  # type: ignore[union-attr]

    # Update meta with appropriate status
    if needs_clarification:
        meta.status = "core_generated_low_context"
        meta.needs_clarification = True
    else:
        meta.status = "core_generated"
        meta.needs_clarification = False

    meta.model = model
    meta.error_message = None
    _save_meta(run_dir, meta)

    rprint(f"[green]ContentCore written:[/green] {core_path}")

    # ── Step 3: Print clarification suggestions (non-blocking) ───────────
    if needs_clarification and clarification_questions:
        rprint()
        rprint("[yellow]Draft generated, but clarification is recommended:[/yellow]")
        for i, q in enumerate(clarification_questions, 1):
            rprint(f"  [bold]{i}.[/bold] {q}")
        rprint()
        rprint(f"[dim]To enrich the core, run: cf clarify {run_id} -m \"your additional context\"[/dim]")


# ── clarify ──────────────────────────────────────────────────────────────────

@app.command()
def clarify(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    message: str = typer.Option(..., "-m", "--message", help="Answers to clarification questions."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
) -> None:
    """Provide answers to clarification questions and update the brief.

    Appends your answers to context_notes in brief.json and resets
    needs_clarification flag so that 'cf core' can produce a richer output.
    """
    run_dir = _resolve_run(output, run_id)

    brief_path_file = run_dir / "brief.json"
    if not brief_path_file.exists():
        rprint(f"[red]Error:[/red] brief.json not found in {run_dir}")
        raise typer.Exit(1)

    brief = Brief.model_validate(read_json(brief_path_file))
    meta = _load_meta(run_dir)

    # Append answers to context_notes
    if brief.context_notes:
        brief.context_notes = brief.context_notes.rstrip() + "\n\n" + message
    else:
        brief.context_notes = message

    write_json(brief_path_file, brief.model_dump())

    # Reset clarification flag and status for re-generation
    meta.status = "clarified"
    meta.needs_clarification = False
    meta.error_message = None
    _save_meta(run_dir, meta)

    rprint("[green]Brief updated with clarification answers.[/green]")
    rprint(f"  [dim]context_notes now includes your input.[/dim]")
    rprint(f"\nRun [bold]cf core {run_id}[/bold] to regenerate the ContentCore with richer context.")


# ── render ───────────────────────────────────────────────────────────────────

@app.command()
def render(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    platform: str = typer.Option("linkedin", "--platform", "-p", help="Platform to render: linkedin (more coming)."),
    model: str = typer.Option("gpt-4o-mini", "--model", "-m", help="OpenAI model to use."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
) -> None:
    """Render a platform-specific draft from ContentCore."""
    if platform not in PLATFORMS:
        rprint(f"[red]Error:[/red] Invalid platform '{platform}'. Choose: {', '.join(PLATFORMS)}")
        raise typer.Exit(1)

    # Currently only linkedin has a full render implementation
    if platform != "linkedin":
        rprint(f"[yellow]Warning:[/yellow] Render for '{platform}' is not yet implemented. Only 'linkedin' is supported.")
        raise typer.Exit(1)

    run_dir = _resolve_run(output, run_id)

    # Load required artifacts
    core_path = run_dir / "core.json"
    if not core_path.exists():
        rprint(f"[red]Error:[/red] core.json not found. Run 'cf core {run_id}' first.")
        raise typer.Exit(1)

    core_data = read_json(core_path)
    if not core_data:
        rprint(f"[red]Error:[/red] core.json is empty. Run 'cf core {run_id}' first.")
        raise typer.Exit(1)

    try:
        core_obj = ContentCore.model_validate(core_data)
    except Exception as exc:
        rprint(f"[red]Error:[/red] Invalid core.json: {exc}")
        raise typer.Exit(1)

    brief = Brief.model_validate(read_json(run_dir / "brief.json"))
    meta = _load_meta(run_dir)
    provider = _make_provider(model)

    rprint(f"[blue]Rendering {platform} draft[/blue] for [bold]{brief.topic}[/bold]...")

    from content_factory.graph import run_render_pipeline

    try:
        rendered, prompt_used, error = run_render_pipeline(
            brief=brief,
            core=core_obj,
            provider=provider,
            platform=platform,
        )
    except Exception as exc:
        error = str(exc)
        rendered = None
        prompt_used = None

    if error:
        meta.status = "error"
        meta.error_message = error
        meta.model = model
        _save_meta(run_dir, meta)
        rprint(f"[red]Error during rendering:[/red] {error}")
        raise typer.Exit(1)

    # Write the rendered draft
    draft_path = artifact_path(run_dir, platform)
    write_text(draft_path, rendered + "\n")  # type: ignore[operator]

    # Save the prompt used for auditability
    if prompt_used:
        save_run_prompt(run_dir, f"{platform}_render.txt", prompt_used)

    # Update meta
    meta.status = f"{platform}_rendered"
    meta.model = model
    meta.error_message = None
    _save_meta(run_dir, meta)

    rprint(f"[green]{platform.capitalize()} draft written:[/green] {draft_path}")
    rprint(f"  [dim]{len(rendered)} chars[/dim]")  # type: ignore[arg-type]


# ── patch ────────────────────────────────────────────────────────────────────

@app.command()
def patch(
    run_id: str = typer.Argument(..., help="Run ID (exact name or prefix)."),
    platform: str = typer.Option(..., "--platform", "-p", help="Platform: blog, linkedin, or x."),
    message: str = typer.Option(..., "-m", "--message", help="Patch directive."),
    model: str = typer.Option("gpt-4o-mini", "--model", help="OpenAI model to use."),
    output: str = typer.Option(DEFAULT_RUNS_DIR, "-o", "--output", help="Base directory for runs."),
) -> None:
    """Apply a patch directive to an existing platform draft.

    Backs up the current version, applies minimal LLM-driven rewrite,
    and saves patch metadata with changelog.
    """
    if platform not in PLATFORMS:
        rprint(f"[red]Error:[/red] Invalid platform '{platform}'. Choose: {', '.join(PLATFORMS)}")
        raise typer.Exit(1)

    run_dir = _resolve_run(output, run_id)

    # Load current draft
    draft_path = artifact_path(run_dir, platform)
    if not draft_path.exists() or draft_path.read_text(encoding="utf-8").strip() == "(pending)":
        rprint(f"[red]Error:[/red] No rendered {platform} draft found. Run 'cf render {run_id} -p {platform}' first.")
        raise typer.Exit(1)

    current_draft = draft_path.read_text(encoding="utf-8")
    meta = _load_meta(run_dir)
    provider = _make_provider(model)

    rprint(f"[blue]Applying patch[/blue] to {platform} draft: [dim]{message}[/dim]")

    from content_factory.graph import run_patch_pipeline

    try:
        patched, changelog, prompt_used, error = run_patch_pipeline(
            draft=current_draft,
            directive=message,
            provider=provider,
        )
    except Exception as exc:
        error = str(exc)
        patched = None
        changelog = None
        prompt_used = None

    if error:
        meta.status = "error"
        meta.error_message = error
        meta.model = model
        _save_meta(run_dir, meta)
        rprint(f"[red]Error during patching:[/red] {error}")
        raise typer.Exit(1)

    # Version the current draft before overwriting
    version_num = version_artifact(run_dir, platform)
    rprint(f"  [dim]Previous version saved as {platform}_v{version_num}.md[/dim]")

    # Write patched draft
    write_text(draft_path, patched + "\n")  # type: ignore[operator]

    # Save prompt used
    if prompt_used:
        patch_num = next_patch_number(run_dir, platform)
        save_run_prompt(run_dir, f"patch_{patch_num:03d}_{platform}.txt", prompt_used)
    else:
        patch_num = next_patch_number(run_dir, platform)

    # Save patch record
    record = PatchRecord(
        patch_number=patch_num,
        platform=platform,
        directive=message,
        model=model,
        changelog=changelog or "",
    )
    record_path = save_patch_record(run_dir, record.model_dump(), platform, patch_num)

    # Update meta
    meta.status = f"{platform}_patched"
    meta.model = model
    meta.error_message = None
    _save_meta(run_dir, meta)

    rprint(f"[green]Patch applied:[/green] {draft_path}")
    if changelog:
        rprint(Panel(changelog, title="Changelog", border_style="dim"))
    rprint(f"  [dim]Patch record: {record_path}[/dim]")


# ── init ────────────────────────────────────────────────────────────────────

EXAMPLE_BRIEF = '''# Example brief for content-factory
# Copy this file and customize for your content

topic: "Your topic here"
goal: "inform"
audience: "your target audience"
platform_targets:
  - blog
  - linkedin
  - x
language: "en"
context_notes: >
  Add your context, examples, data, or personal experience here.
  This is what makes the content specific and non-generic.
constraints:
  tone: "direct, opinionated"
'''

EXAMPLE_STYLE_PROFILE = '''# Style Profile for content-factory
# Controls tone, voice, and anti-patterns.

forbidden_ai_smell:
  description: >
    Phrases that signal AI-generated content. These MUST be avoided.
  avoid_phrases:
    - "in a world where"
    - "let's dive in"
    - "it's no secret that"
    - "in today's fast-paced"
    - "let's unpack"
    - "game-changer"

voice:
  tone: "direct, specific, opinionated"
  perspective: "practitioner sharing real experience"
  avoid:
    - generic advice
    - unsupported claims
    - filler sentences
'''


@app.command()
def init(
    output_dir: str = typer.Option(".", "-o", "--output", help="Directory to create starter files in."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Create starter example brief and style profile files.

    Run this after cloning the repo to get started quickly:
        cf init
        cf init -o ./my-content-setup
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Create example brief
    brief_path = out / "brief.yaml"
    if brief_path.exists() and not force:
        rprint(f"[yellow]Skipped:[/yellow] {brief_path} already exists (use --force to overwrite)")
    else:
        brief_path.write_text(EXAMPLE_BRIEF, encoding="utf-8")
        rprint(f"[green]Created:[/green] {brief_path}")

    # Create style profile
    profile_path = out / "style_profile.yaml"
    if profile_path.exists() and not force:
        rprint(f"[yellow]Skipped:[/yellow] {profile_path} already exists (use --force to overwrite)")
    else:
        profile_path.write_text(EXAMPLE_STYLE_PROFILE, encoding="utf-8")
        rprint(f"[green]Created:[/green] {profile_path}")

    rprint()
    rprint("Next steps:")
    rprint(f"  1. Edit [bold]{brief_path.name}[/bold] with your topic and context")
    rprint(f"  2. Run: [bold]cf generate {brief_path}[/bold]")
    rprint()
    rprint("For private/custom resources, set:")
    rprint("  export CONTENT_FACTORY_PRIVATE_DIR=/path/to/your/private/dir")


if __name__ == "__main__":
    app()
