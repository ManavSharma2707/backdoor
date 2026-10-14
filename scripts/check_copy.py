#!/usr/bin/env python3
"""Copy rules check (ui-copywriting.md section 8).

Three levels, so the docs can talk about banned words but nothing a person reads can use them:

1. Dashes: the em dash (U+2014) and en dash (U+2013) are forbidden everywhere we write text.
   Scanned: context/**, CLAUDE.md, README.md, backend/app, backend/seed, frontend/src.
2. Copy files: banned words, exclamation marks and emoji in every string literal.
   Scanned: frontend/src/copy/**, backend/app/core/messages.py,
   backend/app/engine/report_builder.py, backend/seed/corpus/**.
3. Other frontend source: the same checks, but only for prose strings (containing a space).

Comments are ignored for levels 2 and 3. URLs are ignored. Exit code 1 when anything fails.

Usage: python scripts/check_copy.py [--root PATH]
"""

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DASHES = ("\u2014", "\u2013")
DASH_NAMES = {"\u2014": "em dash", "\u2013": "en dash"}
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f]")
URL = re.compile(r"https?://\S+")
STRING_LITERAL = re.compile(
    r"""(?x)
    '(?:[^'\\\n]|\\.)*'
    | "(?:[^"\\\n]|\\.)*"
    | `(?:[^`\\]|\\.)*`
    """
)
JSX_TEXT = re.compile(r">([^<>{}\n]*[A-Za-z][^<>{}\n]*)<")
LINE_COMMENT = re.compile(r"(?m)^\s*//.*$|(?<=[\s;,)])//[^\n'\"`]*$")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# Directories that hold generated or third party text.
SKIP_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".git", "types"}

DASH_SCAN = (
    ("context", {".md"}),
    ("backend/app", {".py", ".md"}),
    ("backend/seed", {".py", ".md", ".yaml", ".yml", ".txt", ".json"}),
    ("frontend/src", {".ts", ".tsx", ".css", ".md"}),
)
DASH_SCAN_FILES = ("CLAUDE.md", "README.md")
COPY_FILES = (
    "frontend/src/copy",
    "backend/app/core/messages.py",
    "backend/app/engine/report_builder.py",
    "backend/seed/corpus",
)
CORPUS_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def banned_patterns(root: Path) -> list[tuple[str, re.Pattern[str]]]:
    """The single list of banned words lives in backend/app/core/text.py."""
    sys.path.insert(0, str(root / "backend"))
    try:
        from app.core.text import BANNED_WORDS
    finally:
        sys.path.pop(0)
    return [
        (word, re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])", re.IGNORECASE))
        for word in BANNED_WORDS
    ]


def iter_files(base: Path, suffixes: set[str]) -> Iterator[Path]:
    if base.is_file():
        yield base
        return
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.suffix in suffixes and not SKIP_PARTS & set(path.parts):
            yield path


def check_dashes(path: Path, display: str, text: str) -> list[Violation]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for dash in DASHES:
            if dash in line:
                found.append(
                    Violation(display, number, f"{DASH_NAMES[dash]}, use a comma, colon or 'to'")
                )
    return found


def check_string(
    display: str, line: int, value: str, patterns: list[tuple[str, re.Pattern[str]]]
) -> list[Violation]:
    value = URL.sub("", value)
    found = []
    for word, pattern in patterns:
        if pattern.search(value):
            found.append(
                Violation(display, line, f"banned word or phrase '{word}': {value[:60]!r}")
            )
    if "!" in value:
        found.append(Violation(display, line, f"exclamation mark: {value[:60]!r}"))
    if EMOJI.search(value):
        found.append(Violation(display, line, f"emoji: {value[:60]!r}"))
    return found


def python_strings(text: str) -> Iterator[tuple[int, str]]:
    """String constants of a module, without docstrings."""
    tree = ast.parse(text)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.lineno, node.value


def script_strings(text: str, *, prose_only: bool) -> Iterator[tuple[int, str]]:
    """String literals and JSX text of a TypeScript file, comments blanked out."""
    blanked = BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    blanked = LINE_COMMENT.sub("", blanked)
    for match in STRING_LITERAL.finditer(blanked):
        value = match.group(0)[1:-1]
        if prose_only and " " not in value.strip():
            continue
        yield blanked.count("\n", 0, match.start()) + 1, value
    for match in JSX_TEXT.finditer(blanked):
        yield blanked.count("\n", 0, match.start()) + 1, match.group(1).strip()


def check_copy_file(
    path: Path, display: str, text: str, patterns: list[tuple[str, re.Pattern[str]]], *, copy: bool
) -> list[Violation]:
    found: list[Violation] = []
    if path.suffix == ".py":
        try:
            strings = list(python_strings(text))
        except SyntaxError as error:
            return [Violation(display, error.lineno or 1, "file does not parse")]
        for line, value in strings:
            found.extend(check_string(display, line, value, patterns))
    elif path.suffix in {".ts", ".tsx"}:
        for line, value in script_strings(text, prose_only=not copy):
            found.extend(check_string(display, line, value, patterns))
    else:  # corpus text: every line is user facing
        for number, line_text in enumerate(text.splitlines(), start=1):
            found.extend(check_string(display, number, line_text, patterns))
    return found


def scan(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    patterns = banned_patterns(root)

    def read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None

    seen_dash: set[Path] = set()
    for folder, suffixes in DASH_SCAN:
        for path in iter_files(root / folder, suffixes):
            seen_dash.add(path)
    for name in DASH_SCAN_FILES:
        if (root / name).is_file():
            seen_dash.add(root / name)
    for path in sorted(seen_dash):
        text = read(path)
        if text is not None:
            violations.extend(check_dashes(path, path.relative_to(root).as_posix(), text))

    copy_paths: set[Path] = set()
    for entry in COPY_FILES:
        for path in iter_files(root / entry, CORPUS_SUFFIXES | {".py", ".ts", ".tsx"}):
            copy_paths.add(path)
    for path in sorted(copy_paths):
        text = read(path)
        if text is not None:
            display = path.relative_to(root).as_posix()
            violations.extend(check_copy_file(path, display, text, patterns, copy=True))

    for path in iter_files(root / "frontend/src", {".ts", ".tsx"}):
        in_test_helpers = path.relative_to(root / "frontend/src").parts[0] == "test"
        if path in copy_paths or in_test_helpers or path.name.endswith((".test.ts", ".test.tsx", ".d.ts")):
            continue
        text = read(path)
        if text is not None:
            display = path.relative_to(root).as_posix()
            violations.extend(check_copy_file(path, display, text, patterns, copy=False))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check copy rules")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    violations = scan(args.root.resolve())
    for violation in violations:
        print(violation)  # noqa: T201
    if violations:
        print(f"\n{len(violations)} copy problem(s) found.")  # noqa: T201
        return 1
    print("Copy check passed.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
