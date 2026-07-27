#!/usr/bin/env python3
"""Wrap text (not markup) in HTML files to a column width.

Skips content inside style/script/svg (and related) elements so CSS and
vector markup are left alone. Designed for existing pages and generated
HTML under content/.

Usage:
  python3 scripts/wrap-html-text.py [paths...]
  python3 scripts/wrap-html-text.py --width 50 content/**/*.html
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_WIDTH = 50
SKIP_TAGS = {
    "style",
    "script",
    "svg",
    "path",
    "circle",
    "rect",
    "line",
    "polygon",
    "polyline",
    "g",
    "defs",
    "symbol",
    "use",
    "clippath",
    "lineargradient",
    "radialgradient",
    "stop",
    "mask",
    "pattern",
    "text",
    "tspan",
    "foreignobject",
}
VOID_TAGS = {
    "br",
    "hr",
    "img",
    "input",
    "meta",
    "link",
    "area",
    "base",
    "col",
    "embed",
    "source",
    "track",
    "wbr",
}


def current_column(buf: str) -> int:
    i = buf.rfind("\n")
    return len(buf) if i < 0 else len(buf) - i - 1


def line_indent(buf: str) -> str:
    i = buf.rfind("\n")
    line = buf if i < 0 else buf[i + 1 :]
    m = re.match(r"[ \t]*", line)
    return m.group(0) if m else ""


def wrap_core(
    words: list[str],
    *,
    width: int,
    first_budget: int,
    indent: str,
    first_prefix: str,
) -> str:
    """Wrap words onto lines.

    first_prefix is placed before the first word on the first line (e.g. leading
    spaces that belonged to the text node). first_budget is how many columns
    remain on the current line for first_prefix + first line content.

    When content cannot start on the current line, a leading newline is emitted
    so continuation indent does not glue onto the previous markup.
    """
    if not words:
        return first_prefix

    # Pieces joined at the end. The first piece may omit a leading newline
    # (continue after a tag); later pieces always start with "\n" + indent.
    pieces: list[str] = []
    cur: list[str] = []
    on_first_line = True
    prefix = first_prefix
    budget = first_budget

    if budget <= 0:
        # No room on the current line — start a fresh indented line.
        on_first_line = False
        prefix = ""
        budget = max(width - len(indent), 10)
        if first_prefix and not first_prefix.isspace():
            # Unusual non-space prefix with no room; keep it on the new line.
            prefix = first_prefix.lstrip()

    def line_cap() -> int:
        if on_first_line:
            return budget
        return width

    def used_prefix_len() -> int:
        if on_first_line:
            return len(prefix)
        return len(indent)

    def flush() -> None:
        nonlocal cur, on_first_line, prefix, budget
        chunk = " ".join(cur)
        if on_first_line:
            pieces.append(prefix + chunk)
        else:
            pieces.append("\n" + indent + chunk)
        cur = []
        on_first_line = False
        prefix = ""
        budget = max(width - len(indent), 10)

    for w in words:
        if not cur:
            room = line_cap() - used_prefix_len()
            if len(w) > room and used_prefix_len() > 0:
                # Break before this word; drop whitespace-only first prefix.
                if on_first_line and prefix and not prefix.strip():
                    prefix = ""
                elif on_first_line and prefix:
                    # Non-space prefix already committed to this line — emit it
                    # alone only if it has content; otherwise just break.
                    pieces.append(prefix)
                    prefix = ""
                on_first_line = False
                budget = max(width - len(indent), 10)
                cur = [w]
                continue
            if len(w) > room and used_prefix_len() == 0 and on_first_line:
                # Zero used on a mid-line with tiny budget: break first.
                on_first_line = False
                budget = max(width - len(indent), 10)
            cur = [w]
            continue

        tentative = " ".join(cur + [w])
        total = used_prefix_len() + len(tentative)
        if total > line_cap():
            flush()
            cur = [w]
        else:
            cur.append(w)

    if cur:
        flush()
    elif on_first_line and prefix:
        pieces.append(prefix)

    return "".join(pieces)


def wrap_plain(text: str, width: int, first_width: int, indent: str) -> str:
    """Wrap a text node to `width` columns. Preserves lead/trail whitespace.

    Markup is never broken. Short single-token text (e.g. hour digits inside
    spans) is left on the current line even when preceding tags already used
    the column budget — otherwise a forced break would inject visible spaces.
    """
    if not text or text.isspace():
        return text

    if "\n" in text:
        parts = text.split("\n")
        out: list[str] = []
        for idx, part in enumerate(parts):
            if idx == 0:
                out.append(wrap_plain(part, width, first_width, indent))
                continue
            m = re.match(r"^([ \t]*)(.*)$", part, re.DOTALL)
            lead, rest = m.group(1), m.group(2)
            if not rest:
                out.append(part)
                continue
            trail_m = re.search(r"(\s*)$", rest)
            trail = trail_m.group(1) if trail_m else ""
            core = rest[: len(rest) - len(trail)] if trail else rest
            if not core:
                out.append(part)
                continue
            words = core.split()
            # Already on its own line: only wrap if longer than width.
            if len(lead) + len(core) <= width:
                out.append(part)
                continue
            wrapped = wrap_core(
                words,
                width=width,
                first_budget=width,
                indent=lead,
                first_prefix=lead,
            )
            out.append(wrapped + trail)
        return "\n".join(out)

    lead_m = re.match(r"^(\s*)", text)
    lead = lead_m.group(1) if lead_m else ""
    trail_m = re.search(r"(\s*)$", text)
    trail = trail_m.group(1) if trail_m else ""
    core = text[len(lead) : len(text) - len(trail) if trail else len(text)]
    if not core:
        return text

    words = core.split()

    # Fits in the remaining columns on this line — nothing to do.
    if len(lead) + len(core) <= first_width:
        return text

    # Single token (no word breaks): do not force a newline after markup.
    # Allow the source line to exceed the width; the text itself is short.
    if len(words) == 1:
        return text

    # Multi-word text that overruns the remaining budget — wrap it.
    wrapped = wrap_core(
        words,
        width=width,
        first_budget=first_width,
        indent=indent,
        first_prefix=lead,
    )
    return wrapped + trail


def process_html(html: str, width: int = DEFAULT_WIDTH) -> str:
    token_re = re.compile(
        r"(<!--.*?-->|<!\[CDATA\[.*?\]\]>|<!DOCTYPE[^>]*>|<\?.*?\?>|<[^>]+>)",
        re.DOTALL | re.IGNORECASE,
    )
    parts = token_re.split(html)
    skip_stack: list[str] = []
    result: list[str] = []
    tag_name_re = re.compile(r"</?\s*([a-zA-Z0-9:-]+)")

    for part in parts:
        if not part:
            continue
        if part.startswith("<"):
            result.append(part)
            if part.startswith("<!--") or part.startswith("<!") or part.startswith("<?"):
                continue
            m = tag_name_re.match(part)
            if not m:
                continue
            name = m.group(1).lower()
            is_close = part.lstrip().startswith("</")
            is_self = part.rstrip().endswith("/>") or name in VOID_TAGS
            if name in SKIP_TAGS:
                if is_close:
                    if skip_stack and skip_stack[-1] == name:
                        skip_stack.pop()
                elif not is_self:
                    skip_stack.append(name)
            continue

        if skip_stack:
            result.append(part)
            continue

        buf = "".join(result)
        col = current_column(buf)
        ind = line_indent(buf)
        result.append(wrap_plain(part, width, width - col, ind))

    return "".join(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="HTML files to wrap (default: content/**/*.html)",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any file would change; do not write",
    )
    args = parser.parse_args(argv)

    paths = args.paths
    if not paths:
        paths = sorted(Path.cwd().joinpath("content").glob("**/*.html"))
        if not paths:
            print("No HTML files found under content/", file=sys.stderr)
            return 1

    changed = 0
    for path in paths:
        original = path.read_text(encoding="utf-8")
        wrapped = process_html(original, args.width)
        if wrapped != original:
            changed += 1
            if args.check:
                print(f"would wrap: {path}")
            else:
                path.write_text(wrapped, encoding="utf-8")
                print(f"wrapped: {path}")
        else:
            print(f"ok: {path}")

    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
