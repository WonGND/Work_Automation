"""Minimal S-expression reader for KiCad files.

KiCad's board, footprint and schematic files are S-expressions: ``(token
attr attr (child ...) ...)``. Strings may be quoted (``"F.Cu"``, with ``\\"``
and ``\\\\`` escapes) or bare (``F.Cu``, ``smd``, ``1.6``). Atoms are kept
as ``str``; callers convert numbers with :meth:`Node.num` / :meth:`Node.floats`
because a bare ``1`` can be a pad *name* as well as a number.

Reference: KiCad developer documentation, "S-Expression Format",
<https://dev-docs.kicad.org/en/file-formats/sexpr-intro/>.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from pcbsim.errors import ConfigError

_TOKEN = re.compile(r'\(|\)|"((?:[^"\\]|\\.)*)"|([^\s()"]+)', re.S)
_ESC = re.compile(r"\\(.)", re.S)
_ESC_MAP = {"n": "\n", "t": "\t", "r": "\r"}


@dataclass(slots=True, eq=False)
class Node:
    """``(tag arg ...)``; ``args`` holds atoms (``str``) and child nodes in file order."""

    tag: str
    args: list[str | Node] = field(default_factory=list)

    @property
    def atoms(self) -> list[str]:
        return [a for a in self.args if isinstance(a, str)]

    @property
    def children(self) -> list[Node]:
        return [a for a in self.args if isinstance(a, Node)]

    def find(self, tag: str) -> Node | None:
        for a in self.args:
            if isinstance(a, Node) and a.tag == tag:
                return a
        return None

    def find_all(self, tag: str) -> Iterator[Node]:
        for a in self.args:
            if isinstance(a, Node) and a.tag == tag:
                yield a

    def has_atom(self, atom: str) -> bool:
        return any(a == atom for a in self.args if isinstance(a, str))

    def atom(self, i: int = 0, default: str | None = None) -> str:
        at = self.atoms
        if i < len(at):
            return at[i]
        if default is None:
            raise ConfigError(f"({self.tag} ...): missing attribute {i + 1}")
        return default

    def num(self, i: int = 0, default: float | None = None) -> float:
        at = self.atoms
        if i >= len(at):
            if default is None:
                raise ConfigError(f"({self.tag} ...): missing number {i + 1}")
            return default
        try:
            return float(at[i])
        except ValueError:
            raise ConfigError(f"({self.tag} ...): {at[i]!r} is not a number") from None

    def floats(self) -> list[float]:
        out: list[float] = []
        for a in self.atoms:
            try:
                out.append(float(a))
            except ValueError:
                continue
        return out

    def value(self, tag: str, default: str | None = None) -> str | None:
        """First atom of the child ``(tag VALUE)``, or ``default``."""
        n = self.find(tag)
        if n is None or not n.atoms:
            return default
        return n.atoms[0]

    def number(self, tag: str, default: float | None = None) -> float | None:
        n = self.find(tag)
        if n is None or not n.atoms:
            return default
        return n.num(0)

    def xy(self, tag: str) -> tuple[float, float] | None:
        n = self.find(tag)
        if n is None:
            return None
        v = n.floats()
        if len(v) < 2:
            raise ConfigError(f"({tag} ...): expected X Y")
        return v[0], v[1]


def _unescape(s: str) -> str:
    return _ESC.sub(lambda m: _ESC_MAP.get(m.group(1), m.group(1)), s)


def parse(text: str) -> Node:
    """Parse one top-level S-expression; raise :class:`ConfigError` on malformed input."""
    stack: list[Node] = []
    root: Node | None = None
    expect_tag = False
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        if tok == "(":
            if root is not None and not stack:
                raise ConfigError("s-expression: content after the top-level expression")
            expect_tag = True
            continue
        if tok == ")":
            if expect_tag:
                raise ConfigError("s-expression: empty list '()'")
            if not stack:
                raise ConfigError(f"s-expression: unbalanced ')' at offset {m.start()}")
            done = stack.pop()
            if stack:
                stack[-1].args.append(done)
            else:
                root = done
            continue
        atom = _unescape(m.group(1)) if m.group(1) is not None else tok
        if expect_tag:
            stack.append(Node(atom))
            expect_tag = False
        elif stack:
            stack[-1].args.append(atom)
        else:
            raise ConfigError(f"s-expression: atom {atom!r} outside any list")
    if stack or expect_tag:
        raise ConfigError("s-expression: unexpected end of file (unbalanced '(')")
    if root is None:
        raise ConfigError("s-expression: empty document")
    return root
