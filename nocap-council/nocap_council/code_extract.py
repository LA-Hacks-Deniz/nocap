# Owner: DEVIN — Phase 1 task T1.4
"""Python AST -> SymPy converter for the No Cap polygraph.

The Coder role (T1.10) hands us a Python implementation of an algorithm
from a paper; T1.5 (``sympy_match``) needs every assignment in the
function body as a SymPy expression so it can compare against the
LaTeX-side parse. This module owns that conversion.

Public API
----------

``code_to_sympy(code: str, fn_name: str) -> dict[str, sympy.Expr]``
    Parse ``code``, locate the ``def fn_name`` (first match wins), walk
    its body, and return a dict mapping each assigned name to the
    fully-substituted SymPy expression for its value.

    ``self.<attr>`` targets are keyed as ``<attr>`` (the leading
    ``self.`` is stripped). A synthetic ``"_return"`` key holds the
    expression returned by a top-level ``return`` statement, if any.

    Function arguments are *not* pre-seeded into the env; references to
    them in the body fall through to ``sympy.Symbol(name)`` via the
    standard ``visit_Name`` path. This keeps the output dict scoped to
    things the function actually defines.

Conventions worth pinning down (so T1.5 can mirror them on the LaTeX
side):

- Subscripts (``theta[t - 1]``) become ``sympy.Symbol(ast.unparse(node))``
  with the unparsed string used verbatim — i.e. the symbol name is the
  literal source text ``"theta[t - 1]"``, including its spaces. T1.5
  must produce the same string from the LaTeX ``\\theta_{t-1}``.
- ``self.<attr>`` becomes ``Symbol(attr)``.
- ``np.<attr>`` / ``torch.<attr>`` / ``math.<attr>`` (as values, not
  function calls) become ``Symbol(attr)`` — the module prefix is
  always stripped.
- ``a / b`` is true division, ``a // b`` is ``sympy.floor(a / b)``,
  ``a % b`` is ``sympy.Mod(a, b)``.
- Augmented assigns (``x += y``) desugar to ``x = x + y``.
- Annotated assigns (``x: float = 5.0``) are treated as plain assigns;
  the annotation is dropped.

Math functions
--------------

These call names map directly to SymPy primitives, regardless of
whether they're called bare or via ``np.<fn>`` / ``torch.<fn>`` /
``math.<fn>``:

    exp, log, log2, log10, sin, cos, tan, asin, acos, atan, atan2,
    sinh, cosh, tanh, sqrt, abs, sign, floor, ceil, sigmoid (rewritten
    as ``1 / (1 + exp(-x))``), softplus (rewritten as ``log(1 + exp(x))``),
    relu (rewritten as ``Max(0, x)``).

Anything else falls back to ``sympy.Function(name)(*args)`` — opaque,
but participates in structural equality checks.
"""

from __future__ import annotations

import ast
from typing import Any

import sympy as sp

__all__ = ["CodeToSympy", "code_to_sympy"]

_KNOWN_MODULES: frozenset[str] = frozenset({"np", "numpy", "torch", "math", "sp", "sympy"})


def _sigmoid(x: sp.Expr) -> sp.Expr:
    return sp.Integer(1) / (sp.Integer(1) + sp.exp(-x))


def _softplus(x: sp.Expr) -> sp.Expr:
    return sp.log(sp.Integer(1) + sp.exp(x))


def _relu(x: sp.Expr) -> sp.Expr:
    return sp.Max(sp.Integer(0), x)


# Function-name -> SymPy callable. Used by both bare calls (``exp(x)``)
# and module-prefixed calls (``np.exp(x)``); the module prefix is
# stripped before the lookup.
_MATH_FUNCS: dict[str, Any] = {
    "exp": sp.exp,
    "log": sp.log,
    "log2": lambda x: sp.log(x, 2),
    "log10": lambda x: sp.log(x, 10),
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "atan2": sp.atan2,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "sqrt": sp.sqrt,
    "abs": sp.Abs,
    "fabs": sp.Abs,
    "sign": sp.sign,
    "floor": sp.floor,
    "ceil": sp.ceiling,
    "ceiling": sp.ceiling,
    "min": sp.Min,
    "max": sp.Max,
    "minimum": sp.Min,
    "maximum": sp.Max,
    "sigmoid": _sigmoid,
    "softplus": _softplus,
    "relu": _relu,
}

_BINOP_TO_FN: dict[type[ast.operator], Any] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: sp.floor(a / b),
    ast.Mod: lambda a, b: sp.Mod(a, b),
    ast.Pow: lambda a, b: a**b,
    ast.MatMult: lambda a, b: sp.Function("matmul")(a, b),
    ast.LShift: lambda a, b: sp.Function("lshift")(a, b),
    ast.RShift: lambda a, b: sp.Function("rshift")(a, b),
    ast.BitOr: lambda a, b: sp.Function("bitor")(a, b),
    ast.BitXor: lambda a, b: sp.Function("bitxor")(a, b),
    ast.BitAnd: lambda a, b: sp.Function("bitand")(a, b),
}


class CodeToSympy(ast.NodeVisitor):
    """Walks a function body and accumulates ``name -> sympy.Expr`` in ``env``.

    The visitor methods return SymPy expressions for value-producing
    nodes; statement nodes (``Assign``, ``AugAssign``, ``AnnAssign``,
    ``Return``) mutate ``self.env`` and return ``None``.

    A name shadowed by an earlier assign is *substituted* on subsequent
    use — that's how the chain ``self.m = beta1*self.m + (1-beta1)*g``
    followed by ``m_hat = self.m / (1 - beta1**t)`` produces the
    bias-corrected expression rather than a bare ``Symbol("m")`` for
    ``m_hat``.
    """

    def __init__(self, *, strip_self: bool = True) -> None:
        self.env: dict[str, sp.Expr] = {}
        self.strip_self = strip_self

    # ---- value nodes ------------------------------------------------------

    def visit_Constant(self, node: ast.Constant) -> sp.Expr:
        v = node.value
        if isinstance(v, bool):
            return sp.true if v else sp.false
        if isinstance(v, int):
            return sp.Integer(v)
        if isinstance(v, float):
            return sp.Float(v)
        if v is None:
            return sp.Symbol("None")
        return sp.Symbol(repr(v))

    def visit_Name(self, node: ast.Name) -> sp.Expr:
        return self.env.get(node.id, sp.Symbol(node.id))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> sp.Expr:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return sp.Not(operand)
        if isinstance(node.op, ast.Invert):
            return sp.Function("invert")(operand)
        return operand

    def visit_BinOp(self, node: ast.BinOp) -> sp.Expr:
        left = self.visit(node.left)
        right = self.visit(node.right)
        fn = _BINOP_TO_FN.get(type(node.op))
        if fn is None:
            return sp.Function(type(node.op).__name__)(left, right)
        return fn(left, right)

    def visit_BoolOp(self, node: ast.BoolOp) -> sp.Expr:
        vals = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return sp.And(*vals)
        if isinstance(node.op, ast.Or):
            return sp.Or(*vals)
        return sp.Function("boolop")(*vals)

    def visit_Compare(self, node: ast.Compare) -> sp.Expr:
        # Only the simple two-operand case is meaningful for our purposes;
        # chains like ``a < b < c`` collapse to a Function so they don't
        # pretend to be equalities.
        if len(node.ops) == 1 and len(node.comparators) == 1:
            left = self.visit(node.left)
            right = self.visit(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return sp.Eq(left, right)
            if isinstance(op, ast.NotEq):
                return sp.Ne(left, right)
            if isinstance(op, ast.Lt):
                return sp.Lt(left, right)
            if isinstance(op, ast.LtE):
                return sp.Le(left, right)
            if isinstance(op, ast.Gt):
                return sp.Gt(left, right)
            if isinstance(op, ast.GtE):
                return sp.Ge(left, right)
        operands = [self.visit(node.left)] + [self.visit(c) for c in node.comparators]
        return sp.Function("compare")(*operands)

    def visit_Attribute(self, node: ast.Attribute) -> sp.Expr:
        # ``self.x`` -> Symbol("x") (configurable).
        if self.strip_self and isinstance(node.value, ast.Name) and node.value.id == "self":
            return sp.Symbol(node.attr)
        # ``np.something`` / ``torch.something`` -> Symbol("something").
        if isinstance(node.value, ast.Name) and node.value.id in _KNOWN_MODULES:
            return sp.Symbol(node.attr)
        # Anything else: keep the dotted form, with dots replaced so it
        # round-trips as a single SymPy Symbol name.
        return sp.Symbol(ast.unparse(node).replace(".", "_"))

    def visit_Subscript(self, node: ast.Subscript) -> sp.Expr:
        # By design (see module docstring): the symbol *name* is the
        # verbatim source text. T1.5 must produce the same string from
        # the LaTeX side so the two parses can be matched.
        return sp.Symbol(ast.unparse(node))

    def visit_Tuple(self, node: ast.Tuple) -> sp.Expr:
        return sp.Tuple(*[self.visit(e) for e in node.elts])

    def visit_List(self, node: ast.List) -> sp.Expr:
        return sp.Tuple(*[self.visit(e) for e in node.elts])

    def visit_Call(self, node: ast.Call) -> sp.Expr:
        # Strip a known module prefix, then look up the callable name.
        # Method-style calls on arbitrary objects (``foo.bar(x)``) become
        # an opaque ``Function("bar")(x)`` — the receiver is dropped on
        # purpose because we don't want to compare object identity.
        if isinstance(node.func, ast.Attribute):
            fname = node.func.attr
        elif isinstance(node.func, ast.Name):
            fname = node.func.id
        else:
            fname = ast.unparse(node.func).replace(".", "_")
        args = [self.visit(a) for a in node.args]
        # kwargs are silently dropped; see module docstring.
        fn = _MATH_FUNCS.get(fname)
        if fn is None:
            return sp.Function(fname)(*args)
        return fn(*args)

    def visit_IfExp(self, node: ast.IfExp) -> sp.Expr:
        cond = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return sp.Piecewise((body, cond), (orelse, True))

    # ---- statement nodes -------------------------------------------------

    def _assign_target(self, target: ast.expr, value: sp.Expr) -> None:
        if isinstance(target, ast.Name):
            self.env[target.id] = value
        elif isinstance(target, ast.Attribute):
            # ``self.x = ...`` keys to "x"; ``foo.bar = ...`` keys to
            # the dotted-and-flattened form so we don't collide.
            if self.strip_self and isinstance(target.value, ast.Name) and target.value.id == "self":
                self.env[target.attr] = value
            else:
                self.env[ast.unparse(target).replace(".", "_")] = value
        elif isinstance(target, ast.Subscript):
            # Whole subscripted lvalue keyed by its source text, same
            # convention as the rvalue side.
            self.env[ast.unparse(target)] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            # Best-effort destructuring: assign each element name to the
            # un-destructured value. Without runtime info we can't index
            # ``value`` meaningfully, so this is intentionally lossy —
            # T1.5 should treat tuple-assigned names as opaque.
            for elt in target.elts:
                self._assign_target(elt, value)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = self.visit(node.value)
        for target in node.targets:
            self._assign_target(target, value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # x += y desugars to x = x + y (with x's *current* value
        # substituted, just like a plain re-assignment).
        target = node.target
        if isinstance(target, ast.Name):
            current = self.env.get(target.id, sp.Symbol(target.id))
        elif (
            isinstance(target, ast.Attribute)
            and self.strip_self
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            current = self.env.get(target.attr, sp.Symbol(target.attr))
        else:
            current = self.visit(target)
        right = self.visit(node.value)
        fn = _BINOP_TO_FN.get(type(node.op))
        if fn is None:
            new_val: sp.Expr = sp.Function(type(node.op).__name__)(current, right)
        else:
            new_val = fn(current, right)
        self._assign_target(target, new_val)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            return
        value = self.visit(node.value)
        self._assign_target(node.target, value)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            return
        # Last return wins; covers the one-liner case
        # ``def fn(...): return mu + sigma * eps`` where there are no
        # other assigns.
        self.env["_return"] = self.visit(node.value)

    # ---- fallthrough ----------------------------------------------------

    def generic_visit(self, node: ast.AST) -> Any:
        # Unknown statement nodes (``If``, ``For``, ``While``, etc.) are
        # walked normally so any nested assigns / returns inside them
        # still update env. Unknown value nodes fall through to a
        # placeholder Symbol — we'd rather lose information than crash.
        if isinstance(node, ast.expr):
            return sp.Symbol(ast.unparse(node).replace(".", "_"))
        for child in ast.iter_child_nodes(node):
            self.visit(child)


def _find_function(tree: ast.AST, fn_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return node
    raise ValueError(f"function {fn_name!r} not found in code")


def code_to_sympy(code: str, fn_name: str) -> dict[str, sp.Expr]:
    """Parse ``code``, find ``def fn_name``, return its env as ``{name: Expr}``.

    The dict maps every assigned name (with ``self.`` stripped from
    attribute targets) to the SymPy expression representing its value
    after substitution of all earlier assigns. A top-level ``return``
    in the function body adds a synthetic key ``"_return"``.

    Raises ``ValueError`` if no ``def fn_name`` is found in ``code``.
    """
    tree = ast.parse(code)
    fn = _find_function(tree, fn_name)
    visitor = CodeToSympy()
    for stmt in fn.body:
        visitor.visit(stmt)
    return visitor.env
