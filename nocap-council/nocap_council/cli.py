# Owner: DEVIN — Phase 1 task T1.14
"""CLI — pretty-printed wrapper around ``orchestrator.verify``.

Public command (registered as the ``nocap`` console script via
``[project.scripts]`` in ``pyproject.toml``)::

    nocap verify-impl <arxiv-id> <code-file> [--claim TEXT]
                                              [--function TEXT]
                                              [--json]

Renders the orchestrator's JSONL stream live as one dim status line
per stage, then prints the Goal-format verdict block + VIGIL audit +
per-stage timing table at the end. Verdict colour follows the
phase-doc Goal section: green (``pass``), red (``anomaly``), yellow
(``inconclusive``).

``--json`` emits raw line-delimited JSON (the orchestrator's stream
events plus the final verdict dict on its own line) and skips Rich
entirely so a gateway / ``jq`` consumer sees zero ANSI codes.

The CLI does not own any verification logic — it borrows the
orchestrator's heuristic helpers (``_normalize_equation``,
``_heuristic_target_var``, ``_is_self_referential``) so the
"equation N" index it prints exactly matches the equation the
matcher actually compared.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nocap_council import code_extract
from nocap_council import orchestrator as orch
from nocap_council.orchestrator import (
    _heuristic_target_var,
    _is_self_referential,
    _normalize_equation,
)

# ----------------------------------------------------------------------
# Helpers — derive display fields from the augmented verdict dict
# ----------------------------------------------------------------------

_OFFLINE_STUB_PREFIX = "[NOCAP_OFFLINE stub] "


def _equation_index(
    claim: dict[str, Any],
    code_env: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[int | None, str | None]:
    """Return ``(1-based_index, raw_equation)`` for the matched equation.

    Walks ``claim["claimed_equations"]`` running the same
    normalize / self-ref-skip / heuristic-target dance the orchestrator
    used. The first equation whose derived ``target_var`` equals
    ``evidence["target_var"]`` is the one the matcher actually
    compared. Returns ``(None, None)`` when no equation matches (e.g.
    structural / hyperparametric strategies don't carry a target_var).
    """
    target = evidence.get("target_var")
    if not target:
        return None, None
    equations = claim.get("claimed_equations") or []
    for idx, raw_eq in enumerate(equations, start=1):
        norm = _normalize_equation(raw_eq)
        derived = _heuristic_target_var(norm, code_env)
        if _is_self_referential(norm, derived):
            continue
        if derived == target:
            return idx, raw_eq
    return None, None


def _code_line_for(code_str: str, target_var: str | None) -> tuple[int | None, str | None]:
    """Find the source line where ``target_var`` is assigned.

    Walks the code's AST, picks the **last** assignment whose target's
    name (or ``self.<name>``) equals ``target_var`` (matching
    ``code_extract``'s post-substitution semantics — the matcher reads
    the post-loop value). Returns ``(lineno, source_line)`` or
    ``(None, None)`` when the target isn't assigned.
    """
    if not target_var:
        return None, None
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return None, None
    candidates: list[ast.Assign] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == target_var:
                candidates.append(node)
                break
            if (
                isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "self"
                and tgt.attr == target_var
            ):
                candidates.append(node)
                break
    if not candidates:
        return None, None
    last = candidates[-1]
    lines = code_str.splitlines()
    if 1 <= last.lineno <= len(lines):
        return last.lineno, lines[last.lineno - 1].strip()
    return last.lineno, None


def _critic_summary(feedback: str | None) -> str | None:
    """First-sentence summary of the Critic's feedback.

    Strips the ``[NOCAP_OFFLINE stub]`` prefix defensively (we're live
    by default but the stub will leak if someone runs ``--offline`` by
    hand) and returns the first sentence — split on ``.`` / ``!`` /
    ``?`` followed by whitespace, falling back to the whole feedback
    when the text has no sentence terminators. ``None`` when there is
    no feedback or it's only the stub prefix.
    """
    if not feedback:
        return None
    text = feedback.strip()
    if text.startswith(_OFFLINE_STUB_PREFIX):
        text = text[len(_OFFLINE_STUB_PREFIX) :].lstrip()
    if not text:
        return None
    m = re.search(r"[.!?](?:\s|$)", text)
    if m:
        return text[: m.start() + 1].strip()
    return text


# ----------------------------------------------------------------------
# Render helpers — Rich
# ----------------------------------------------------------------------

_VERDICT_STYLE: dict[str, tuple[str, str]] = {
    "pass": ("🟢", "bold green"),
    "anomaly": ("🔴", "bold red"),
    "inconclusive": ("🟡", "bold yellow"),
}


def _stage_status_line(event: dict[str, Any]) -> Text:
    """Render one streamed JSONL event as a dim one-line status."""
    stage = event.get("stage", "?")
    status = event.get("status", "?")
    ms = event.get("ms")
    info = event.get("info") or {}
    suffix_parts: list[str] = []

    if stage == "code" and "strategy_idx" in event:
        suffix_parts.append(f"strategy_idx={event['strategy_idx']}")
        suffix_parts.append(f"kind={info.get('kind')}")
        if status == "ok":
            suffix_parts.append(f"equivalent={info.get('equivalent')}")
            if info.get("residual_short"):
                suffix_parts.append(f"residual={info.get('residual_short')}")
            if info.get("critic_score") is not None:
                suffix_parts.append(f"critic_score={info.get('critic_score')}")
        else:
            err = str(info.get("error", ""))
            suffix_parts.append(f"error={err[:60]}")
    elif stage == "spec":
        suffix_parts.append(f"section={info.get('paper_section')!r}")
        suffix_parts.append(f"n_equations={info.get('n_equations')}")
    elif stage == "plan":
        suffix_parts.append(f"kinds={info.get('kinds')}")
    elif stage == "code_extract":
        suffix_parts.append(f"fn_name={info.get('fn_name')}")
        suffix_parts.append(f"n_env_keys={info.get('n_env_keys')}")
    elif stage == "paper_extract":
        suffix_parts.append(f"n_sections={info.get('n_sections')}")
    elif stage == "polygraph":
        suffix_parts.append(f"verdict={info.get('verdict')}")
        suffix_parts.append(f"confidence={info.get('confidence')}")

    suffix = "  " + "  ".join(suffix_parts) if suffix_parts else ""
    ms_str = f"{ms / 1000:>6.2f}s" if isinstance(ms, int | float) else "  --  "
    style = "dim" if status == "ok" else "yellow"
    return Text(f"  [{stage:<14}] {status:<5} {ms_str}{suffix}", style=style)


def _render_pass(console: Console, verdict: dict[str, Any]) -> None:
    confidence = verdict.get("confidence", 0.0)
    body = Text("✓ Implementation matches paper claim", style="bold green")
    console.print(
        Panel(
            body,
            title=f"🟢 Pass — confidence {confidence:.2f}",
            border_style="green",
            padding=(1, 2),
        )
    )


def _render_anomaly(
    console: Console,
    verdict: dict[str, Any],
    code_str: str,
    code_env: dict[str, Any],
) -> None:
    confidence = verdict.get("confidence", 0.0)
    claim = verdict.get("claim") or {}
    section = claim.get("paper_section") or "?"

    icon, style = _VERDICT_STYLE["anomaly"]
    console.print(
        Text.assemble(
            (f"\n{icon} Anomaly detected — confidence {confidence:.2f}\n", style),
        )
    )

    rendered_any = False
    for ev in verdict.get("evidences") or []:
        if ev.get("equivalent"):
            continue
        rendered_any = True
        kind = ev.get("kind", "?")
        idx, raw_eq = _equation_index(claim, code_env, ev)
        target = ev.get("target_var")
        residual = ev.get("residual")
        critic = _critic_summary(ev.get("critic_feedback"))
        eq_label = f"equation {idx}" if idx else "claim"
        line_no, line_src = _code_line_for(code_str, target)

        body = Text()
        eq_text = raw_eq or "(structural / hyperparametric — see mismatches below)"
        body.append("Paper ", style="bold")
        body.append(f"{section}, {eq_label}: ", style="bold cyan")
        body.append(f"{eq_text}\n", style="white")
        if line_no and line_src:
            body.append(f"Code line {line_no}: ", style="bold cyan")
            body.append(f"{line_src}\n", style="white")
        if residual:
            body.append("Residual: ", style="bold cyan")
            body.append(f"{residual}", style="white")
            if critic:
                body.append(f"   ({critic})", style="dim italic")
            body.append("\n")
        elif critic:
            body.append("Critic: ", style="bold cyan")
            body.append(f"{critic}\n", style="dim italic")

        mismatches = ev.get("mismatches") or []
        if mismatches:
            body.append("Mismatches:\n", style="bold cyan")
            for mm in mismatches[:5]:
                body.append(
                    f"  • {mm.get('type')}: expected={mm.get('expected')!r} "
                    f"actual={mm.get('actual')!r} severity={mm.get('severity')}\n",
                    style="white",
                )
            if len(mismatches) > 5:
                body.append(f"  … {len(mismatches) - 5} more\n", style="dim")

        title = f"[{kind}] strategy reported inequivalence"
        console.print(Panel(body, title=title, border_style="red", padding=(1, 2)))

    if not rendered_any:
        # All evidences equivalent but verdict=anomaly → VIGIL role
        # flagged something. Show a generic anomaly panel.
        body = Text(
            "All matcher evidences are equivalent but the VIGIL audit "
            "flagged the run. See the audit section below.",
            style="white",
        )
        console.print(Panel(body, title="[anomaly] VIGIL flag", border_style="red", padding=(1, 2)))


def _render_inconclusive(console: Console, verdict: dict[str, Any]) -> None:
    confidence = verdict.get("confidence", 0.0)
    summary = verdict.get("evidence_summary") or "(no summary)"
    body = Text(summary, style="white")
    console.print(
        Panel(
            body,
            title=f"🟡 Inconclusive — confidence {confidence:.2f}",
            border_style="yellow",
            padding=(1, 2),
        )
    )


def _render_vigil(console: Console, verdict: dict[str, Any]) -> None:
    audit = verdict.get("vigil_audit") or []
    if not audit:
        return
    body = Text()
    for entry in audit:
        role = entry.get("role", "?")
        passed = entry.get("pass", False)
        note = entry.get("note", "")
        marker = "[green]✓[/green]" if passed else "[red]✗[/red]"
        body.append_text(Text.from_markup(f"  {marker} "))
        body.append(f"{role:<14}", style="bold")
        body.append(f" {note}\n", style="white")
    console.print(Panel(body, title="VIGIL audit", border_style="cyan", padding=(0, 2)))


def _render_timing_table(console: Console, events: list[dict[str, Any]]) -> None:
    table = Table(title="Per-stage timings", show_header=True, header_style="bold cyan")
    table.add_column("Stage", style="white")
    table.add_column("Status", style="white")
    table.add_column("ms", justify="right", style="white")
    table.add_column("Detail", style="dim")
    total_ms = 0
    for e in events:
        stage = e.get("stage", "?")
        if stage == "done":
            continue
        status = e.get("status", "?")
        ms = e.get("ms", 0)
        if isinstance(ms, int | float):
            total_ms += int(ms)
        info = e.get("info") or {}
        if stage == "code" and "strategy_idx" in e:
            stage = f"code[{e['strategy_idx']}:{info.get('kind', '?')}]"
            detail_bits = []
            if "equivalent" in info:
                detail_bits.append(f"equivalent={info['equivalent']}")
            if info.get("critic_score") is not None:
                detail_bits.append(f"critic_score={info['critic_score']}")
            detail = "  ".join(detail_bits)
        elif stage == "spec":
            detail = f"section={info.get('paper_section')!r}, eqs={info.get('n_equations')}"
        elif stage == "plan":
            detail = f"kinds={info.get('kinds')}"
        elif stage == "polygraph":
            detail = f"verdict={info.get('verdict')}"
        else:
            detail = ""
        status_style = "green" if status == "ok" else "yellow"
        table.add_row(stage, f"[{status_style}]{status}[/{status_style}]", f"{ms}", detail)
    table.add_row("[bold]total[/bold]", "", f"[bold]{total_ms}[/bold]", "", end_section=True)
    console.print(table)


# ----------------------------------------------------------------------
# Click commands
# ----------------------------------------------------------------------


def _silence_noisy_loggers() -> None:
    """Mute the third-party libs that spam INFO-level requests.

    ``google_genai`` and ``httpx`` log every Gemma / Flash-Lite call at
    INFO. Without this the Rich stream interleaves their lines between
    our dim status rows and looks ugly. Set ``NOCAP_DEBUG_LOGS=1`` to
    keep them.
    """
    import os

    if os.environ.get("NOCAP_DEBUG_LOGS") == "1":
        return
    for name in ("google_genai", "google_genai.models", "httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


@click.group()
def cli() -> None:
    """No Cap — paper-vs-code verifier council CLI."""
    _silence_noisy_loggers()


@cli.command("verify-impl")
@click.argument("arxiv_id", type=str)
@click.argument(
    "code_file",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, path_type=Path),
)
@click.option(
    "--claim",
    "claim_text",
    type=str,
    default=None,
    help="Free-text claim to focus the Spec extractor (passed as user_msg).",
)
@click.option(
    "--function",
    "function_name",
    type=str,
    default=None,
    help="Override the heuristic function-name resolution (e.g. 'step').",
)
@click.option(
    "--json",
    "json_mode",
    is_flag=True,
    default=False,
    help="Emit raw line-delimited JSON (stream events + final verdict). No Rich, no ANSI.",
)
def verify_impl(
    arxiv_id: str,
    code_file: Path,
    claim_text: str | None,
    function_name: str | None,
    json_mode: bool,
) -> None:
    """Verify ``CODE_FILE`` against arXiv paper ``ARXIV_ID``."""
    code_str = code_file.read_text(encoding="utf-8")
    console = Console()
    events: list[dict[str, Any]] = []

    if json_mode:
        # Pure JSONL pipe-through — no Rich, no decoration, just the
        # orchestrator's stream events and the final verdict dict.
        def stream_json(ev: dict[str, Any]) -> None:
            events.append(ev)
            sys.stdout.write(json.dumps(ev) + "\n")
            sys.stdout.flush()

        verdict = orch.verify(
            arxiv_id,
            code_str,
            user_msg=claim_text,
            function_name=function_name,
            stream=stream_json,
        )
        sys.stdout.write(json.dumps(verdict, default=str) + "\n")
        sys.stdout.flush()
        sys.exit(0 if verdict.get("verdict") == "pass" else 1)

    # Rich path — one dim status line per event during streaming.
    console.print(
        Text.assemble(
            ("nocap verify-impl ", "bold cyan"),
            (f"{arxiv_id} ", "white"),
            (str(code_file), "white"),
        )
    )

    def stream_rich(ev: dict[str, Any]) -> None:
        events.append(ev)
        console.print(_stage_status_line(ev))

    verdict = orch.verify(
        arxiv_id,
        code_str,
        user_msg=claim_text,
        function_name=function_name,
        stream=stream_rich,
    )

    # Re-extract code_env for the equation-index helper. The orchestrator
    # already did this once; redoing it is cheap (AST + sympy) and saves
    # us a second public-API change.
    fn_name = verdict.get("function_name") or "step"
    try:
        code_env = code_extract.code_to_sympy(code_str, fn_name)
    except Exception:
        code_env = {}

    console.print()  # spacer
    kind = verdict.get("verdict", "inconclusive")
    if kind == "pass":
        _render_pass(console, verdict)
    elif kind == "anomaly":
        _render_anomaly(console, verdict, code_str, code_env)
    else:
        _render_inconclusive(console, verdict)

    _render_vigil(console, verdict)

    elapsed = verdict.get("elapsed_seconds")
    if isinstance(elapsed, int | float):
        console.print(Text(f"\nTotal wall clock: {elapsed:.2f}s", style="bold"))

    _render_timing_table(console, events)

    sys.exit(0 if kind == "pass" else 1)


if __name__ == "__main__":
    cli()
