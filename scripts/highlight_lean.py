#!/usr/bin/env python3
"""Highlight a Lean snippet as HTML spans. Keywords, attributes, and comments only."""

from __future__ import annotations

import html
import re

KEYWORDS = frozenset(
    {
        "def",
        "structure",
        "where",
        "deriving",
        "do",
        "let",
        "if",
        "then",
        "else",
        "return",
        "private",
        "partial",
        "open",
        "fun",
        "for",
        "in",
        "mut",
        "match",
        "with",
        "import",
        "none",
        "some",
        "by",
    }
)

IDENT = re.compile(r"[A-Za-z_α-ωΑ-Ω][A-Za-z0-9_α-ωΑ-Ω'!?]*")
ATTRIBUTE = re.compile(r"@\[[^\]]+\]")


def highlight_lean(source: str) -> str:
    """Return HTML for a Lean snippet. Input must not contain unmatched comment starters."""
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        if source.startswith("/-", i):
            end = source.find("-/", i + 2)
            if end < 0:
                end = n
            else:
                end += 2
            out.append(f'<span class="cm">{html.escape(source[i:end])}</span>')
            i = end
            continue
        if source.startswith("--", i):
            end = source.find("\n", i)
            if end < 0:
                end = n
            out.append(f'<span class="cm">{html.escape(source[i:end])}</span>')
            i = end
            continue
        attr = ATTRIBUTE.match(source, i)
        if attr is not None:
            out.append(f'<span class="at">{html.escape(attr.group())}</span>')
            i = attr.end()
            continue
        ident = IDENT.match(source, i)
        if ident is not None:
            token = ident.group()
            cls = "kw" if token in KEYWORDS else None
            escaped = html.escape(token)
            out.append(f'<span class="{cls}">{escaped}</span>' if cls else escaped)
            i = ident.end()
            continue
        out.append(html.escape(source[i]))
        i += 1
    return "".join(out)


def highlight_block(source: str) -> str:
    return '<pre class="lean"><code>' + highlight_lean(source.rstrip() + "\n") + "</code></pre>"
