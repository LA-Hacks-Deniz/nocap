# Owner: DEVIN — Phase 1 task T1.25 (v3 — decoupled Spec, Stage 6: code-side claim)
"""Code-side claim extraction.

Produces a structured ``CodeClaim`` from a Python source string + target
function name, mirroring the shape of :class:`nocap_council.spec.Claim`
but sourced from a deterministic AST walk instead of an LLM.

The shape:

    function_name           the resolved target function
    parameters              positional parameter names (incl. ``self``)
    initial_conditions      assignments executed before ``step`` runs
                            (typically class ``__init__`` body, e.g.
                            ``self.m = np.zeros_like(self.theta)``).
    counters                ``x = x ± literal`` patterns inside the
                            target function (loop bookkeeping).
    computed_equations      every other ``Assign`` inside the target
                            function rendered as ``LHS = RHS``.
    hyperparams             ``self.X = Y`` assignments in ``__init__``
                            where Y is a numeric default tied to a
                            keyword argument (lr, beta1, beta2, eps, ...).
    return_value            unparsed RHS of the ``return`` statement.

The matcher pairs the paper Pass-1 ``Claim`` against this ``CodeClaim``
LHS-by-LHS. Equations whose paper LHS resolves to a name in
``parameters`` (gradient-as-input, etc.) are gated out of verification —
those are external-contract equations, not internally-computable
pipeline math.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class CodeClaim:
    function_name: str
    parameters: list[str] = field(default_factory=list)
    initial_conditions: list[str] = field(default_factory=list)
    counters: list[str] = field(default_factory=list)
    computed_equations: list[str] = field(default_factory=list)
    hyperparams: dict[str, str] = field(default_factory=dict)
    return_value: str = ""

    def to_dict(self) -> dict:
        return {
            "function_name": self.function_name,
            "parameters": list(self.parameters),
            "initial_conditions": list(self.initial_conditions),
            "counters": list(self.counters),
            "computed_equations": list(self.computed_equations),
            "hyperparams": dict(self.hyperparams),
            "return_value": self.return_value,
        }


def _unparse(node: ast.AST) -> str:
    """Wrapper around ``ast.unparse`` that returns ``""`` for None."""
    if node is None:
        return ""
    return ast.unparse(node)


def _lhs_name(target: ast.AST) -> str | None:
    """Return a canonical string form of an assignment LHS, or None."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        # Render `self.x` / `obj.attr` form.
        return _unparse(target)
    return None


def _is_counter_pattern(target: ast.AST, value: ast.AST) -> bool:
    """Match ``x = x ± literal`` or ``self.x = self.x ± literal``.

    Both LHS and RHS reference the SAME identifier (or attribute), and
    the RHS is a binary add/sub against a numeric literal.
    """
    if not isinstance(value, ast.BinOp):
        return False
    if not isinstance(value.op, (ast.Add, ast.Sub)):
        return False

    target_str = _lhs_name(target)
    if target_str is None:
        return False

    left_str = _lhs_name(value.left)
    if left_str != target_str:
        return False

    right = value.right
    if isinstance(right, ast.Constant) and isinstance(right.value, (int, float)):
        return True
    # Handle `x = x + (-1)` etc. via the unary-minus sub-tree.
    if (
        isinstance(right, ast.UnaryOp)
        and isinstance(right.op, (ast.USub, ast.UAdd))
        and isinstance(right.operand, ast.Constant)
        and isinstance(right.operand.value, (int, float))
    ):
        return True
    return False


def _find_target_function(
    module: ast.Module, function_name: str
) -> tuple[ast.FunctionDef, ast.ClassDef | None]:
    """Locate ``function_name`` as a top-level function or a method.

    Returns ``(func_def, parent_class_or_None)``. Raises ``KeyError``
    when not found.
    """
    # Top-level functions first.
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node, None
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name:
            return node, None  # type: ignore[return-value]

    # Then class methods.
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == function_name
                ):
                    return child, node  # type: ignore[return-value]

    raise KeyError(f"function {function_name!r} not found in module")


def _find_init_method(class_def: ast.ClassDef) -> ast.FunctionDef | None:
    for child in class_def.body:
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name == "__init__"
        ):
            return child  # type: ignore[return-value]
    return None


def _func_param_names(func: ast.FunctionDef) -> list[str]:
    """Collect positional + kwonly parameter names (skipping *args / **kw)."""
    names: list[str] = []
    args = func.args
    for a in (args.posonlyargs or []):
        names.append(a.arg)
    for a in (args.args or []):
        names.append(a.arg)
    for a in (args.kwonlyargs or []):
        names.append(a.arg)
    return names


def _hyperparam_default_map(init: ast.FunctionDef) -> dict[str, str]:
    """Map kwarg name → default literal repr for ``__init__`` keyword args.

    Only keeps numeric or boolean defaults — the kinds the matcher cares
    about (lr=1e-3, beta1=0.9, eps=1e-8, etc.).
    """
    defaults_map: dict[str, str] = {}
    args = init.args
    pos_args = (args.posonlyargs or []) + (args.args or [])
    pos_defaults = list(args.defaults or [])
    # ``defaults`` aligns with the END of (posonlyargs + args).
    if pos_defaults:
        offset = len(pos_args) - len(pos_defaults)
        for i, default in enumerate(pos_defaults):
            arg = pos_args[offset + i]
            if isinstance(default, ast.Constant) and isinstance(
                default.value, (int, float, bool)
            ):
                defaults_map[arg.arg] = repr(default.value)
    for a, d in zip(args.kwonlyargs or [], args.kw_defaults or []):
        if d is None:
            continue
        if isinstance(d, ast.Constant) and isinstance(d.value, (int, float, bool)):
            defaults_map[a.arg] = repr(d.value)
    return defaults_map


def _extract_init_body(
    init: ast.FunctionDef, init_kwarg_defaults: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Walk ``__init__`` body — split into initial_conditions vs hyperparams.

    Heuristic:
      * ``self.X = <name>`` where the name is a kwarg of ``__init__`` and
        we have a default for it → hyperparam (key=X, value=default).
      * Anything else (``self.X = literal``, ``self.X = np.zeros_like(...)``,
        etc.) → initial_conditions.

    Returns ``(initial_conditions, hyperparams)``.
    """
    initial_conditions: list[str] = []
    hyperparams: dict[str, str] = {}
    for stmt in init.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            initial_conditions.append(_unparse(stmt))
            continue
        target = stmt.targets[0]
        target_str = _lhs_name(target)
        if target_str is None:
            initial_conditions.append(_unparse(stmt))
            continue
        # ``self.X = <Name>`` where Name is a kwarg with a numeric default.
        if (
            isinstance(target, ast.Attribute)
            and isinstance(stmt.value, ast.Name)
            and stmt.value.id in init_kwarg_defaults
        ):
            attr = target.attr
            hyperparams[attr] = init_kwarg_defaults[stmt.value.id]
            continue
        initial_conditions.append(_unparse(stmt))
    return initial_conditions, hyperparams


def _extract_function_body(
    func: ast.FunctionDef,
) -> tuple[list[str], list[str], str]:
    """Walk the target function body.

    Returns ``(counters, computed_equations, return_value)``.
    """
    counters: list[str] = []
    computed_equations: list[str] = []
    return_value = ""

    for stmt in func.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                computed_equations.append(_unparse(stmt))
                continue
            target = stmt.targets[0]
            if _is_counter_pattern(target, stmt.value):
                counters.append(_unparse(stmt))
            else:
                computed_equations.append(_unparse(stmt))
        elif isinstance(stmt, ast.AugAssign):
            # ``x += 1`` is also a counter when RHS is a literal.
            value = stmt.value
            if isinstance(stmt.op, (ast.Add, ast.Sub)) and (
                (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, (int, float))
                )
                or (
                    isinstance(value, ast.UnaryOp)
                    and isinstance(value.op, (ast.USub, ast.UAdd))
                    and isinstance(value.operand, ast.Constant)
                    and isinstance(value.operand.value, (int, float))
                )
            ):
                counters.append(_unparse(stmt))
            else:
                computed_equations.append(_unparse(stmt))
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            computed_equations.append(_unparse(stmt))
        elif isinstance(stmt, ast.Return):
            return_value = _unparse(stmt.value)
        # Skip Expr / docstrings / etc.

    return counters, computed_equations, return_value


def extract_code_claim(code_str: str, function_name: str) -> CodeClaim:
    """Build a :class:`CodeClaim` from ``code_str`` for ``function_name``.

    No LLM. Pure AST walk. Symmetric to
    :func:`nocap_council.spec.extract_paper_claim` so the matcher can
    pair the two structured claims LHS-by-LHS.
    """
    module = ast.parse(code_str)
    func, parent_class = _find_target_function(module, function_name)
    parameters = _func_param_names(func)

    initial_conditions: list[str] = []
    hyperparams: dict[str, str] = {}
    if parent_class is not None:
        init = _find_init_method(parent_class)
        if init is not None:
            kw_defaults = _hyperparam_default_map(init)
            initial_conditions, hyperparams = _extract_init_body(init, kw_defaults)

    counters, computed_equations, return_value = _extract_function_body(func)

    return CodeClaim(
        function_name=function_name,
        parameters=parameters,
        initial_conditions=initial_conditions,
        counters=counters,
        computed_equations=computed_equations,
        hyperparams=hyperparams,
        return_value=return_value,
    )
