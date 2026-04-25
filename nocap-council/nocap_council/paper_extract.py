# Owner: DEVIN — Phase 1 task T1.3
"""paper_extract.py — arXiv source -> structured paper dict for No Cap.

Adapted from research.md [H2] §8 drop-in module. Two public entry points:

    fetch_arxiv_source(arxiv_id: str) -> Path
        Download and (if needed) un-tar/un-gzip the arXiv e-print bundle for
        ``arxiv_id`` into the cache directory and return the local source dir.
        Cache root is taken from the ``NOCAP_ARXIV_CACHE`` env var, defaulting
        to ``/tmp/nocap_arxiv``.

    parse_paper(source_dir: Path) -> dict
        Walk the main ``.tex`` file with a (section, subsection) cursor and
        bucket every display equation, ``algorithm`` float, hyperparameter
        and regex-detected architecture phrase under the section name it
        appears in. Returns::

            {
                "_main_file": "<filename>.tex",
                "<section name>": {
                    "equations": [...],
                    "algorithms": [...],
                    "hyperparams": {...},
                    "architecture": [...],
                },
                ...
            }

        For PDF-only papers (no LaTeX source on arXiv), returns
        ``{"_error": "no_latex_source", "source_dir": "..."}``.

The schema is keyed by section name so downstream council roles
(`spec.py` → Formulator, `polygraph.py` → VIGIL Verifier) can pin claims
to a specific paper section. Section names are normalized: LaTeX commands
inside the heading (``\\emph{...}``, ``\\textbf{...}``, etc.) are stripped
and whitespace is collapsed so that, e.g., ``"§3 Initialization \\emph{Bias}
Correction"`` and ``"Initialization Bias Correction"`` collide on the same
key.
"""

from __future__ import annotations

import gzip
import io
import os
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

import requests
from TexSoup import TexSoup

UA = "nocap-council/0.1 (https://github.com/LA-Hacks-Deniz/nocap)"
DEFAULT_CACHE = "/tmp/nocap_arxiv"

# Display-style math envs we treat as "equations". Inline ``$ ... $`` is
# explicitly skipped (per [H2] §3 — too noisy for verification).
EQ_ENVS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "displaymath",
)

# Algorithmicx step commands. ``re.split`` keeps the captured group, so we
# pair (cmd, body) two-at-a-time below.
STEP_CMDS = (
    r"\\(State|Require|Ensure|Return|For|EndFor|While|EndWhile|If|Else|"
    r"ElsIf|EndIf|Repeat|Until|Procedure|EndProcedure|Function|EndFunction|"
    r"Comment|Loop|EndLoop)"
)
STEP_RE = re.compile(STEP_CMDS)

# `<sym> = <val>` inside ``$ ... $`` — also greedily allow optional `\` on
# Greek letters and ``\times 10^{-N}`` / ``10^{-N}`` exponentials.
HYPER_RE = re.compile(
    r"\$\s*\\?([A-Za-z][A-Za-z_0-9]*|\\[A-Za-z]+(?:_\{?[^}$]+\}?)?)"
    r"\s*=\s*"
    r"([-+]?\d*\.?\d+(?:\s*\\times\s*10\^\{?-?\d+\}?)?|10\^\{?-?\d+\}?)"
    r"\s*\$"
)

# Architecture phrases — e.g. "3-layer MLP with ReLU activation",
# "12 layer Transformer", "two-layer LSTM". Captures depth (optional),
# type, activation (optional). Matches against section text (post-LaTeX
# command stripping).
LAYER_RE = re.compile(
    r"(?P<depth>\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"[\s\-]?layer\s+"
    r"(?P<type>MLP|CNN|Transformer|RNN|LSTM|GRU|ResNet|U-?Net|GNN|VAE)"
    r"(?:\s+with\s+(?P<activation>[A-Za-z][A-Za-z0-9]*)\s+activation)?",
    re.IGNORECASE,
)
WORD_TO_INT = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Strip ``\section{Foo \emph{Bar} Baz}`` -> ``Foo Bar Baz``. We collapse
# any ``\cmd{...}`` (with optional ``*``) to its inner text and drop any
# leftover ``\cmd`` plus its ``{...}`` arg even when we don't keep it.
_LATEX_CMD_WITH_ARG = re.compile(r"\\[A-Za-z]+\*?\s*\{([^{}]*)\}")
_LATEX_CMD_DROP_ARG = re.compile(
    r"\\(?:vspace|hspace|label|footnote|cite[a-z]*|ref|eqref|protect)\*?\s*\{[^{}]*\}"
)
_LATEX_CMD_BARE = re.compile(r"\\[A-Za-z]+\*?")


def _normalize_section_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw
    # First drop noise commands whose argument we don't want
    # (``\vspace{-.1in}``, ``\label{...}``, ``\cite{...}``).
    for _ in range(3):
        new = _LATEX_CMD_DROP_ARG.sub("", s)
        if new == s:
            break
        s = new
    # Then flatten ``\cmd{inner}`` -> ``inner`` for emphasis-style commands.
    for _ in range(4):
        new = _LATEX_CMD_WITH_ARG.sub(r"\1", s)
        if new == s:
            break
        s = new
    s = _LATEX_CMD_BARE.sub("", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _looks_like_pdf_wrapper(target: Path) -> bool:
    """Detect arXiv submissions that are a thin LaTeX shell around \\includepdf.

    Some authors upload only a PDF; arXiv accepts that by wrapping it in a
    minimal ``article`` document that just ``\\includepdf``s the file.
    Adam's published version (1412.6980 latest) is one such — there is no
    real LaTeX body to extract from. We detect that here so a downstream
    caller can retry with an earlier version that has full source.
    """
    tex_files = list(target.rglob("*.tex"))
    if not tex_files:
        return False
    pdfs = list(target.rglob("*.pdf"))
    if not pdfs:
        return False
    for p in tex_files:
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        if r"\includepdf" in txt and r"\section" not in txt:
            return True
    return False


def _fetch_one(arxiv_id: str, target: Path) -> None:
    r = requests.get(
        f"https://arxiv.org/e-print/{arxiv_id}",
        headers={"User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()

    if r.headers.get("Content-Type", "").startswith("application/pdf"):
        (target / "paper.pdf").write_bytes(r.content)
        return

    buf = io.BytesIO(r.content)
    try:
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            tar.extractall(target)
        return
    except tarfile.ReadError:
        pass
    try:
        data = gzip.decompress(r.content)
    except OSError:
        data = r.content
    (target / "main.tex").write_bytes(data)


def fetch_arxiv_source(arxiv_id: str, out_root: Path | None = None) -> Path:
    """Download arXiv e-print for ``arxiv_id`` and return its local source dir.

    Cache root: ``out_root`` if provided, else ``$NOCAP_ARXIV_CACHE``, else
    ``/tmp/nocap_arxiv``. Re-uses any existing populated cache dir.

    If the latest version is a ``\\includepdf`` wrapper (the upload was
    PDF-only), automatically retries with ``v1``..``v3`` until a real
    LaTeX source is found. Falls back to the wrapper directory if every
    version is PDF-only.
    """
    if out_root is None:
        out_root = Path(os.environ.get("NOCAP_ARXIV_CACHE", DEFAULT_CACHE))
    out_root.mkdir(parents=True, exist_ok=True)
    target = out_root / arxiv_id.replace("/", "_")

    # Cache hit — but if it's a PDF wrapper, we still need to walk versions.
    if target.exists() and any(target.iterdir()):
        if not _looks_like_pdf_wrapper(target):
            return target
    else:
        target.mkdir(parents=True, exist_ok=True)
        _fetch_one(arxiv_id, target)
        if not _looks_like_pdf_wrapper(target):
            return target

    # Retry earlier versions, newest-first, so we get the closest-to-canonical
    # LaTeX content that isn't itself a PDF wrapper. (For 1412.6980 the latest
    # is the wrapper but v8 down to v3 have full LaTeX with the canonical
    # default hyperparameters; v1/v2 have older preliminary defaults.)
    for n in range(9, 0, -1):
        version = f"v{n}"
        alt = out_root / f"{arxiv_id.replace('/', '_')}_{version}"
        if alt.exists() and any(alt.iterdir()):
            if not _looks_like_pdf_wrapper(alt):
                return alt
            continue
        alt.mkdir(parents=True, exist_ok=True)
        try:
            _fetch_one(f"{arxiv_id}{version}", alt)
        except requests.HTTPError:
            continue
        if not _looks_like_pdf_wrapper(alt):
            return alt
    return target


def _find_main_tex(src: Path) -> Path | None:
    candidates = [p for p in src.rglob("*.tex") if r"\documentclass" in p.read_text(errors="replace")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _inline_inputs(tex: str, base: Path, depth: int = 0) -> str:
    if depth > 5:
        return tex

    def repl(m: re.Match[str]) -> str:
        name = m.group(1).strip()
        path = base / (name if name.endswith(".tex") else name + ".tex")
        if path.exists():
            return _inline_inputs(path.read_text(errors="replace"), base, depth + 1)
        return ""

    tex = re.sub(r"\\input\{([^}]+)\}", repl, tex)
    tex = re.sub(r"\\include\{([^}]+)\}", repl, tex)
    return tex


# ----------------------------------------------------------------------
# Author-defined ``\newcommand`` macro expansion (T1.25 v3 follow-up).
#
# Some papers (e.g. Adam, arXiv 1412.6980) define LaTeX shortcuts in the
# preamble — ``\newcommand{\wm}{\hat{m}}`` — and use them inside the
# main algorithm. If we hand the raw ``\wm`` token to Gemma, the
# downstream matcher's symbol heuristic doesn't know ``wm == \hat{m}``,
# so the matcher misses the bias-correction equations entirely.
#
# We do a deterministic preamble pass that scans for ``\newcommand``
# (and ``\renewcommand`` / ``\providecommand``) definitions, captures
# their bodies via brace-balanced extraction, removes the definitions
# from the source, and substitutes references throughout. Macros with
# numbered arguments (``\newcommand{\foo}[1]{\bar{#1}}``) are handled.
# ``\def``, conditionals, recursive macros, ``[default]`` arguments,
# and other exotic forms fall through unexpanded — we log a stderr
# warning per skipped macro and let downstream parsing see the raw
# token (which usually still works fine for non-critical macros).
# ----------------------------------------------------------------------

_NEWCOMMAND_HEAD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\s*\\([A-Za-z]+)\*?\s*\}?"
)


def _find_balanced(text: str, start: int) -> int:
    """Given ``text[start] == '{'``, return the index of the matching ``}``.

    Returns ``-1`` if no balanced match exists. Skips ``\\{`` / ``\\}``
    escapes so an escaped brace inside the body doesn't unbalance the
    scan.
    """
    if start >= len(text) or text[start] != "{":
        return -1
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            # Skip the escaped char (handles \{, \}, \\).
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_newcommand_definitions(
    tex: str,
) -> tuple[dict[str, tuple[int, str]], list[tuple[int, int]]]:
    """Scan ``tex`` for ``\\newcommand``-shaped macro definitions.

    Returns ``(defs, spans)`` where ``defs`` maps ``name -> (n_args, body)``
    and ``spans`` is a list of ``(start, end)`` byte ranges covering each
    full definition (so the caller can splice them out before
    substitution to avoid re-detecting them).
    """
    defs: dict[str, tuple[int, str]] = {}
    spans: list[tuple[int, int]] = []
    for m in _NEWCOMMAND_HEAD_RE.finditer(tex):
        name = m.group(1)
        i = m.end()
        # Skip whitespace between macro head and optional [N] / body brace.
        while i < len(tex) and tex[i] in " \t\n":
            i += 1
        n_args = 0
        # Optional ``[N]`` argument count.
        if i < len(tex) and tex[i] == "[":
            close = tex.find("]", i)
            if close == -1:
                continue
            try:
                n_args = int(tex[i + 1 : close].strip())
            except ValueError:
                # Skip exotic forms like ``[1][default]`` we don't model.
                print(
                    f"[paper_extract] WARNING: skipping \\{name} — "
                    f"non-integer arg count in {tex[i:close + 1]!r}",
                    file=sys.stderr,
                )
                continue
            i = close + 1
            while i < len(tex) and tex[i] in " \t\n":
                i += 1
            # Optional ``[default]`` for first arg — skip it as not modelled.
            if i < len(tex) and tex[i] == "[":
                close2 = tex.find("]", i)
                if close2 == -1:
                    continue
                i = close2 + 1
                while i < len(tex) and tex[i] in " \t\n":
                    i += 1
        if i >= len(tex) or tex[i] != "{":
            continue
        end = _find_balanced(tex, i)
        if end == -1:
            continue
        body = tex[i + 1 : end]
        # Recursive self-reference would loop substitution forever.
        if re.search(r"\\" + re.escape(name) + r"(?![A-Za-z])", body):
            print(
                f"[paper_extract] WARNING: skipping \\{name} — "
                f"recursive self-reference in body",
                file=sys.stderr,
            )
            continue
        # Last definition wins (matches LaTeX semantics for renewcommand).
        defs[name] = (n_args, body)
        spans.append((m.start(), end + 1))
    return defs, spans


def _strip_spans(tex: str, spans: list[tuple[int, int]]) -> str:
    """Remove ``spans`` (byte ranges) from ``tex`` in reverse order."""
    if not spans:
        return tex
    spans = sorted(spans, key=lambda s: -s[0])
    parts = list(tex)
    for s, e in spans:
        del parts[s:e]
    return "".join(parts)


def _substitute_macro(tex: str, name: str, n_args: int, body: str) -> str:
    """Replace every ``\\name`` reference in ``tex`` with its expanded body.

    For ``n_args > 0``, reads that many ``{...}`` argument groups
    immediately following the reference and substitutes them for ``#1``,
    ``#2`` etc. in ``body``. If the expected argument groups are
    missing, leaves the reference unchanged.
    """
    pattern = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z])")
    out_parts: list[str] = []
    i = 0
    for m in pattern.finditer(tex):
        out_parts.append(tex[i : m.start()])
        cursor = m.end()
        if n_args == 0:
            out_parts.append(body)
            i = cursor
            continue
        # Read N argument groups, each ``{...}`` (possibly preceded by ws).
        args: list[str] | None = []
        cur = cursor
        for _ in range(n_args):
            while cur < len(tex) and tex[cur] in " \t":
                cur += 1
            if cur >= len(tex) or tex[cur] != "{":
                args = None
                break
            close = _find_balanced(tex, cur)
            if close == -1:
                args = None
                break
            args.append(tex[cur + 1 : close])
            cur = close + 1
        if args is None:
            # Couldn't read enough args — keep the reference as-is.
            out_parts.append(m.group(0))
            i = cursor
        else:
            expanded = body
            for k, a in enumerate(args, start=1):
                expanded = expanded.replace(f"#{k}", a)
            out_parts.append(expanded)
            i = cur
    out_parts.append(tex[i:])
    return "".join(out_parts)


def _expand_newcommand_macros(tex: str, max_passes: int = 5) -> str:
    """Expand author-defined ``\\newcommand`` macros throughout ``tex``.

    Removes the definitions from the source and applies substitutions
    iteratively up to ``max_passes`` times so nested macros (one body
    references another) get fully resolved. A no-change pass terminates
    early.
    """
    defs, spans = _parse_newcommand_definitions(tex)
    if not defs:
        return tex
    tex = _strip_spans(tex, spans)
    for _ in range(max_passes):
        new_tex = tex
        for name, (n_args, body) in defs.items():
            try:
                new_tex = _substitute_macro(new_tex, name, n_args, body)
            except Exception as e:
                print(
                    f"[paper_extract] WARNING: macro \\{name} expansion "
                    f"failed: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
        if new_tex == tex:
            break
        tex = new_tex
    return tex


def _parse_algorithm(node: Any) -> dict[str, Any]:
    caption = node.find("caption")
    label = node.find("label")
    inner = node.find("algorithmic") or node
    parts = STEP_RE.split(str(inner))
    steps: list[dict[str, Any]] = []
    # ``re.split`` returns [pre, cap1, body1, cap2, body2, ...].
    for i in range(1, len(parts), 2):
        cmd = parts[i]
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        steps.append({"cmd": cmd, "text": text, "line": len(steps) + 1})
    return {
        "name": str(caption.string) if caption and caption.string else None,
        "label": str(label.string) if label and label.string else None,
        "steps": steps,
        "raw": str(node),
    }


def _equation_record(env: str, node: Any) -> dict[str, Any]:
    label_node = node.find("label")
    label = str(label_node.string) if label_node and label_node.string else None
    return {"env": env, "latex": str(node), "label": label}


def _strip_latex_for_prose(tex: str) -> str:
    """Best-effort plain-prose view of ``tex`` for regex passes."""
    s = tex
    for _ in range(4):
        new = _LATEX_CMD_WITH_ARG.sub(r"\1", s)
        if new == s:
            break
        s = new
    s = _LATEX_CMD_BARE.sub(" ", s)
    s = s.replace("{", " ").replace("}", " ")
    return s


def _extract_hyperparams(tex: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for sym, val in HYPER_RE.findall(tex):
        sym = sym.lstrip("\\")
        val = val.replace("\\times", "*").strip()
        # Normalize ``10^{-8}`` / ``10^-8`` -> ``1e-8``.
        m = re.fullmatch(r"10\^\{?(-?\d+)\}?", val)
        if m:
            val = f"1e{int(m.group(1))}"
        m = re.fullmatch(r"([-+]?\d*\.?\d+)\s*\*\s*10\^\{?(-?\d+)\}?", val)
        if m:
            val = f"{m.group(1)}e{int(m.group(2))}"
        out.setdefault(sym, val)
    return out


def _extract_architecture(prose: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in LAYER_RE.finditer(prose):
        depth_raw = m.group("depth").lower()
        depth: int | None
        if depth_raw.isdigit():
            depth = int(depth_raw)
        else:
            depth = WORD_TO_INT.get(depth_raw)
        out.append(
            {
                "depth": depth,
                "type": m.group("type"),
                "activation": m.group("activation"),
                "raw": m.group(0).strip(),
            }
        )
    return out


def _section_spans(tex: str) -> list[tuple[int, int, str]]:
    """Return ``[(start, end, section_name)]`` covering every byte of ``tex``.

    The first span (if non-empty) is keyed ``_preamble``; subsequent spans
    correspond to ``\\section{...}`` boundaries. Nested ``\\subsection``s are
    flattened into their parent section because section *names* are what the
    Formulator pins claims to.
    """
    sec_re = re.compile(r"\\section\*?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
    matches = list(sec_re.finditer(tex))
    if not matches:
        return [(0, len(tex), "_preamble")]
    out: list[tuple[int, int, str]] = []
    if matches[0].start() > 0:
        out.append((0, matches[0].start(), "_preamble"))
    for i, m in enumerate(matches):
        name = _normalize_section_name(m.group(1)) or "_unsectioned"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(tex)
        out.append((start, end, name))
    return out


def _section_for_pos(spans: list[tuple[int, int, str]], pos: int) -> str:
    for start, end, name in spans:
        if start <= pos < end:
            return name
    return "_unsectioned"


def _empty_bucket() -> dict[str, Any]:
    return {
        "equations": [],
        "algorithms": [],
        "hyperparams": {},
        "architecture": [],
    }


def _find_env_spans(tex: str, env: str) -> list[tuple[int, int, str]]:
    """Return ``[(start, end, body)]`` for every ``\\begin{env} ... \\end{env}``."""
    out: list[tuple[int, int, str]] = []
    begin = re.compile(r"\\begin\{" + re.escape(env) + r"\}(\[[^\]]*\])?")
    end = re.compile(r"\\end\{" + re.escape(env) + r"\}")
    pos = 0
    while True:
        m = begin.search(tex, pos)
        if not m:
            break
        e = end.search(tex, m.end())
        if not e:
            break
        out.append((m.start(), e.end(), tex[m.start() : e.end()]))
        pos = e.end()
    return out


def parse_paper(source_dir: Path) -> dict[str, Any]:
    """Return the section-keyed extraction dict for the paper at ``source_dir``.

    Every value in the returned dict is itself a dict, so callers can safely
    iterate ``d.values()`` and call ``.get('equations', [])`` on each entry
    without a type check.
    """
    main = _find_main_tex(source_dir)
    if main is None:
        return {
            "_error": {
                "reason": "no_latex_source",
                "source_dir": str(source_dir),
            }
        }

    tex = _inline_inputs(main.read_text(errors="replace"), main.parent)
    # Expand author-defined ``\newcommand`` macros (e.g. Adam's
    # ``\wm`` / ``\wv`` for ``\hat{m}`` / ``\hat{v}``) before parsing
    # so downstream consumers see canonical LaTeX.
    tex = _expand_newcommand_macros(tex)

    out: dict[str, Any] = {}
    spans = _section_spans(tex)
    # Pre-seed every section bucket so downstream consumers can rely on
    # the keys existing.
    for _, _, name in spans:
        out.setdefault(name, _empty_bucket())

    # Equations: TexSoup finds ``\begin{equation}`` / ``\begin{align}`` etc.
    # but mis-orders ``$$ ... $$`` and ``\[ ... \]``. Use a position-aware
    # regex pass for the latter and a raw-text scan for the former so each
    # equation is bucketed under the section it physically appears in.
    try:
        soup: Any | None = TexSoup(tex)
    except Exception:
        soup = None

    def _node_pos(node: Any, latex: str) -> int:
        # TexSoup sets ``.position`` to the byte offset of ``\begin{env}``
        # in the source. Fall back to a substring search if that isn't set
        # or whitespace differences make it unusable.
        pos = getattr(node, "position", None)
        if isinstance(pos, int) and pos >= 0:
            return pos
        return tex.find(latex)

    if soup is not None:
        for env in EQ_ENVS:
            try:
                nodes = soup.find_all(env)
            except Exception:
                nodes = []
            for node in nodes:
                latex = str(node)
                pos = _node_pos(node, latex)
                section = _section_for_pos(spans, pos) if pos >= 0 else "_unsectioned"
                rec = _equation_record(env, node)
                out.setdefault(section, _empty_bucket())["equations"].append(rec)
        try:
            algo_nodes = soup.find_all("algorithm")
        except Exception:
            algo_nodes = []
        for node in algo_nodes:
            latex = str(node)
            pos = _node_pos(node, latex)
            section = _section_for_pos(spans, pos) if pos >= 0 else "_unsectioned"
            out.setdefault(section, _empty_bucket())["algorithms"].append(_parse_algorithm(node))

    # Backstop: TexSoup occasionally drops nested envs. Scan raw tex for any
    # ``\begin{env}...\end{env}`` we missed and fold them in by position.
    for env in EQ_ENVS:
        for start, _end, body in _find_env_spans(tex, env):
            section = _section_for_pos(spans, start)
            bucket = out.setdefault(section, _empty_bucket())
            if any(eq["latex"] == body for eq in bucket["equations"]):
                continue
            label_m = re.search(r"\\label\{([^}]+)\}", body)
            bucket["equations"].append(
                {
                    "env": env,
                    "latex": body,
                    "label": label_m.group(1) if label_m else None,
                }
            )
    for start, _end, body in _find_env_spans(tex, "algorithm"):
        section = _section_for_pos(spans, start)
        bucket = out.setdefault(section, _empty_bucket())
        if any(a.get("raw") == body for a in bucket["algorithms"]):
            continue
        try:
            node = TexSoup(body).find("algorithm")
        except Exception:
            node = None
        if node is None:
            label_m = re.search(r"\\label\{([^}]+)\}", body)
            cap_m = re.search(r"\\caption\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body)
            parts = STEP_RE.split(body)
            steps: list[dict[str, Any]] = []
            for i in range(1, len(parts), 2):
                cmd = parts[i]
                text = parts[i + 1].strip() if i + 1 < len(parts) else ""
                steps.append({"cmd": cmd, "text": text, "line": len(steps) + 1})
            bucket["algorithms"].append(
                {
                    "name": cap_m.group(1) if cap_m else None,
                    "label": label_m.group(1) if label_m else None,
                    "steps": steps,
                    "raw": body,
                }
            )
        else:
            bucket["algorithms"].append(_parse_algorithm(node))

    # ``$$ ... $$`` and ``\[ ... \]`` display math.
    for m in re.finditer(r"\$\$(.+?)\$\$", tex, re.DOTALL):
        section = _section_for_pos(spans, m.start())
        out.setdefault(section, _empty_bucket())["equations"].append(
            {"env": "displaymath", "latex": m.group(0), "label": None}
        )
    for m in re.finditer(r"\\\[(.+?)\\\]", tex, re.DOTALL):
        section = _section_for_pos(spans, m.start())
        out.setdefault(section, _empty_bucket())["equations"].append(
            {"env": "displaymath", "latex": m.group(0), "label": None}
        )

    # Per-section hyperparam + architecture passes.
    for start, end, name in spans:
        body = tex[start:end]
        bucket = out.setdefault(name, _empty_bucket())
        for sym, val in _extract_hyperparams(body).items():
            bucket["hyperparams"].setdefault(sym, val)
        # Also harvest hyperparams from algorithm ``\Require``/``\REQUIRE``
        # lines that fall in this section — Adam declares its defaults in
        # the algorithm caption, not in prose.
        for alg in bucket["algorithms"]:
            for sym, val in _extract_hyperparams(alg.get("raw", "")).items():
                bucket["hyperparams"].setdefault(sym, val)
        bucket["architecture"].extend(_extract_architecture(_strip_latex_for_prose(body)))

    # Drop empty sections so the Formulator isn't drowned in noise. Keep
    # internal keys (``_preamble``) untouched.
    for k in list(out.keys()):
        if k.startswith("_"):
            continue
        v = out[k]
        if not v["equations"] and not v["algorithms"] and not v["hyperparams"] and not v["architecture"]:
            del out[k]

    return out


if __name__ == "__main__":
    import json
    import sys

    arxiv_id = sys.argv[1] if len(sys.argv) > 1 else "1412.6980"
    src = fetch_arxiv_source(arxiv_id)
    parsed = parse_paper(src)
    print(json.dumps(parsed, indent=2)[:4000])
