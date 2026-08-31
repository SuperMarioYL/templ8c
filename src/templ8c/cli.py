"""templ8c CLI - render a model's chat template and check it for conformance.

Two commands cover the m1 happy path:

    templ8c render --model glm-5.3-flash --message "What's the weather?"
    templ8c check  --model glm-5.3-flash

``check --server`` is accepted but the live server probe lands in m3; in m1 it
falls back to a template-only check with a notice.
"""

from __future__ import annotations

import typer
from rich.console import Console

from . import __version__
from .checker import Checker
from .reference.specs import SUPPORTED_MODELS

app = typer.Typer(
    name="templ8c",
    help="Chat-template conformance checker for CN model releases.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def render(
    model: str = typer.Option(..., "--model", "-m", help="Model id, e.g. glm-5.3-flash."),
    message: str = typer.Option(
        "What's the weather in SF?", "--message", help="A single user message to render."
    ),
) -> None:
    """Render a model's reference chat template with one user message."""
    out = Checker().render(model, message)
    console.print(out)


@app.command()
def check(
    model: str = typer.Option(..., "--model", "-m", help="Model id, e.g. glm-5.3-flash."),
    server: str | None = typer.Option(
        None,
        "--server",
        help="Probe an inference server (vllm|sglang). m1 checks the template only.",
    ),
) -> None:
    """Check a model's chat template against its ConformanceSpec."""
    result = Checker().check(model)
    console.print()
    console.print(f"[bold]templ8c v{__version__}[/bold] - chat template conformance checker")
    console.print(f"Model: [cyan]{result.model_id}[/cyan]")
    console.print("Template source: bundled reference (tokenizer_config.json)")
    if server:
        console.print(
            f"[yellow]Server probe ({server}) is not implemented in m1; "
            "checking template rendering only.[/yellow]"
        )

    from rich.table import Table

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Field")
    table.add_column("Expected")
    table.add_column("Actual")
    table.add_column("Status")
    for diff in result.diffs:
        style = "green" if diff.status == "PASS" else "red"
        table.add_row(
            diff.field,
            diff.expected,
            diff.actual,
            f"[{style}]{diff.status}[/{style}]",
        )
    console.print(table)

    if result.failed_count:
        console.print(f"\n[red]FAIL: {result.failed_count} field(s) did not conform.[/red]")
        raise typer.Exit(code=1)
    console.print("\n[green]PASS: all fields conform to the reference spec.[/green]")


@app.command(name="models")
def models() -> None:
    """List supported model families."""
    console.print("[bold]Supported model families:[/bold]")
    for mid in SUPPORTED_MODELS:
        console.print(f"  - {mid}")


if __name__ == "__main__":
    app()
