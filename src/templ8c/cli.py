"""templ8c CLI - render a model's chat template and check it for conformance.

    templ8c render --model glm-5.3-flash --message "What's the weather?"
    templ8c check  --model glm-5.3-flash
    templ8c check  --model glm-5.3-flash --tokenizer-config tokenizer_config.json
    templ8c check  --model glm-5.3-flash --source hf:zai-org/GLM-5.3
    templ8c check  --model glm-5.3-flash --server vllm --server-url http://localhost:8000

Without ``--tokenizer-config``/``--source`` the check compares the bundled
reference template against its spec; the flags point it at a real model's
tokenizer_config.json instead. ``--server`` additionally probes what an
inference server (vllm|sglang) actually renders for the same test cases.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .checker import Checker
from .reference.specs import SUPPORTED_MODELS
from .server_probe import DEFAULT_SERVER_URL, SUPPORTED_SERVERS, ProbeError, ServerProbe
from .template_loader import TemplateLoader

app = typer.Typer(
    name="templ8c",
    help="Chat-template conformance checker for CN model releases.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"templ8c {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the templ8c version and exit.",
    ),
) -> None:
    """Chat-template conformance checker for CN model releases."""


def _fail(message: str) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _load_template_option(
    tokenizer_config: Path | None, source: str | None
) -> tuple[str | None, str]:
    """Resolve the optional template-source flags.

    Returns ``(template_source or None, human description)``; the description
    is only meaningful when a template was resolved.
    """
    if tokenizer_config is not None and source is not None:
        raise typer.BadParameter("--tokenizer-config and --source are mutually exclusive")

    loader = TemplateLoader()
    if tokenizer_config is not None:
        try:
            template = loader.load_from_tokenizer_config(tokenizer_config)
        except (OSError, ValueError) as exc:
            _fail(f"failed to load {tokenizer_config}: {exc}")
        return template, f"tokenizer_config.json (local: {tokenizer_config})"

    if source is not None:
        scheme, sep, ref = source.partition(":")
        if not sep or not ref or scheme not in ("hf", "modelscope"):
            raise typer.BadParameter(
                "--source must be hf:<repo_id> or modelscope:<model_id>"
            )
        try:
            if scheme == "hf":
                template = loader.load_from_hf(ref)
                return template, f"tokenizer_config.json (HuggingFace: {ref})"
            template = loader.load_from_modelscope(ref)
            return template, f"tokenizer_config.json (ModelScope: {ref})"
        except (ValueError, httpx.HTTPError) as exc:
            _fail(f"failed to fetch tokenizer_config.json for {source}: {exc}")

    return None, "bundled reference (tokenizer_config.json)"


@app.command()
def render(
    model: str = typer.Option(..., "--model", "-m", help="Model id, e.g. glm-5.3-flash."),
    message: str = typer.Option(
        "What's the weather in SF?", "--message", help="A single user message to render."
    ),
    tokenizer_config: Path | None = typer.Option(
        None,
        "--tokenizer-config",
        help="Render this tokenizer_config.json template instead of the bundled one.",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Fetch the template from hf:<repo_id> or modelscope:<model_id>.",
    ),
) -> None:
    """Render a model's chat template with one user message."""
    template, _ = _load_template_option(tokenizer_config, source)
    try:
        out = Checker().render(model, message, template_source=template)
    except ValueError as exc:
        _fail(str(exc))
    console.print(out)


def _print_result_table(result, title: str) -> None:
    console.print(f"[bold]{title}[/bold]")
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
        console.print(f"[red]FAIL: {result.failed_count} field(s) did not conform.[/red]")
    else:
        console.print("[green]PASS: all fields conform to the reference spec.[/green]")


@app.command()
def check(
    model: str = typer.Option(..., "--model", "-m", help="Model id, e.g. glm-5.3-flash."),
    server: str | None = typer.Option(
        None,
        "--server",
        help="Additionally probe an inference server (vllm|sglang).",
    ),
    server_url: str = typer.Option(
        DEFAULT_SERVER_URL,
        "--server-url",
        help=f"Base URL of the inference server (default: {DEFAULT_SERVER_URL}).",
    ),
    tokenizer_config: Path | None = typer.Option(
        None,
        "--tokenizer-config",
        help="Check this tokenizer_config.json template instead of the bundled one.",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Fetch the template from hf:<repo_id> or modelscope:<model_id>.",
    ),
) -> None:
    """Check a model's chat template against its ConformanceSpec."""
    if server is not None and server not in SUPPORTED_SERVERS:
        raise typer.BadParameter(
            f"--server must be one of: {', '.join(SUPPORTED_SERVERS)}"
        )
    template, template_desc = _load_template_option(tokenizer_config, source)
    checker = Checker()
    try:
        if template is not None:
            result = checker.check_source(model, template)
        else:
            result = checker.check(model)
    except ValueError as exc:
        _fail(str(exc))

    console.print()
    console.print(f"[bold]templ8c v{__version__}[/bold] - chat template conformance checker")
    console.print(f"Model: [cyan]{result.model_id}[/cyan]")
    console.print(f"Template source: {template_desc}")
    _print_result_table(result, "Template check")
    failed = result.failed_count

    if server is not None:
        probe = ServerProbe(server, server_url)
        try:
            server_result = checker.check_server(model, probe)
        except ProbeError as exc:
            _fail(str(exc))
        console.print()
        console.print(f"Server probe: {server} @ {probe.base_url}")
        _print_result_table(server_result, "Server check")
        failed += server_result.failed_count

    if failed:
        raise typer.Exit(code=1)


@app.command(name="models")
def models() -> None:
    """List supported model families."""
    console.print("[bold]Supported model families:[/bold]")
    for mid in SUPPORTED_MODELS:
        console.print(f"  - {mid}")


if __name__ == "__main__":
    app()
