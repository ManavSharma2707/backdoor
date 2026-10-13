"""The copy checker catches what it should and leaves alone what it should."""

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
EM = "\u2014"
EN = "\u2013"


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_copy", REPO / "scripts" / "check_copy.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_copy"] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A miniature repo with the real banned word list."""
    core = tmp_path / "backend" / "app" / "core"
    core.mkdir(parents=True)
    shutil.copy(REPO / "backend" / "app" / "core" / "text.py", core / "text.py")
    (tmp_path / "context").mkdir()
    (tmp_path / "frontend" / "src" / "copy").mkdir(parents=True)
    (tmp_path / "backend" / "seed" / "corpus").mkdir(parents=True)
    return tmp_path


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def problems(root: Path) -> list[str]:
    return [str(v) for v in checker.scan(root)]


def test_the_repository_itself_is_clean() -> None:
    assert problems(REPO) == []


def test_clean_tree_passes(tree: Path) -> None:
    write(tree, "context/notes.md", "Plain text with a hyphen-ated word.\n")
    write(tree, "frontend/src/copy/en.ts", 'export const en = { save: "Save bill" };\n')
    assert problems(tree) == []


class TestDashes:
    @pytest.mark.parametrize("dash", [EM, EN])
    def test_context_files_may_not_contain_long_dashes(self, tree: Path, dash: str) -> None:
        write(tree, "context/spec.md", f"line one\nstock {dash} order\n")
        result = problems(tree)
        assert len(result) == 1
        assert result[0].startswith("context/spec.md:2:")

    def test_claude_md_is_checked(self, tree: Path) -> None:
        write(tree, "CLAUDE.md", f"rule {EM} rule\n")
        assert any(p.startswith("CLAUDE.md:1") for p in problems(tree))

    def test_backend_source_comments_are_checked_for_dashes(self, tree: Path) -> None:
        write(tree, "backend/app/services/thing.py", f"# note {EN} here\nx = 1\n")
        assert any("thing.py:1" in p for p in problems(tree))

    def test_context_files_may_talk_about_banned_words(self, tree: Path) -> None:
        write(tree, "context/ui-copywriting.md", "Banned: seamless, robust, just, insights!\n")
        assert problems(tree) == []

    def test_generated_folders_are_skipped(self, tree: Path) -> None:
        write(tree, "frontend/src/node_modules/x.ts", f'export const a = "{EM}";\n')
        assert problems(tree) == []


class TestCopyFiles:
    def test_banned_words_in_the_frontend_copy_file(self, tree: Path) -> None:
        write(tree, "frontend/src/copy/en.ts", 'export const en = { a: "A seamless export" };\n')
        result = problems(tree)
        assert len(result) == 1
        assert "seamless" in result[0]

    def test_single_word_strings_are_checked_in_copy_files(self, tree: Path) -> None:
        write(tree, "frontend/src/copy/en.ts", 'export const en = { a: "Insights" };\n')
        assert any("insights" in p.lower() for p in problems(tree))

    def test_exclamation_marks_and_emoji(self, tree: Path) -> None:
        write(
            tree,
            "frontend/src/copy/en.ts",
            'export const en = { a: "Saved!", b: "Done \U0001f389" };\n',
        )
        result = problems(tree)
        assert any("exclamation" in p for p in result)
        assert any("emoji" in p for p in result)

    def test_backend_message_module_strings_are_checked_but_comments_are_not(
        self, tree: Path
    ) -> None:
        write(
            tree,
            "backend/app/core/messages.py",
            '"""Docstring may say seamless."""\n# a comment may say robust\nMSG = "Easily done"\n',
        )
        result = problems(tree)
        assert len(result) == 1
        assert "easily" in result[0].lower()

    def test_words_inside_longer_words_are_fine(self, tree: Path) -> None:
        write(tree, "backend/app/core/messages.py", 'MSG = "Adjust the smartphone justify"\n')
        assert problems(tree) == []

    def test_corpus_text_is_checked_line_by_line(self, tree: Path) -> None:
        write(tree, "backend/seed/corpus/policy.md", "Fine line.\nLeverage this supplier.\n")
        result = problems(tree)
        assert len(result) == 1
        assert "policy.md:2" in result[0]

    def test_urls_are_ignored(self, tree: Path) -> None:
        write(tree, "backend/seed/corpus/links.md", "See https://example.com/just-simply!\n")
        assert problems(tree) == []


class TestOtherFrontendSource:
    def test_prose_strings_are_checked(self, tree: Path) -> None:
        write(tree, "frontend/src/features/x.tsx", 'const t = "Save the bill easily";\n')
        assert any("easily" in p for p in problems(tree))

    def test_code_like_strings_are_not(self, tree: Path) -> None:
        write(tree, "frontend/src/features/x.tsx", 'const c = "just"; const k = "smart";\n')
        assert problems(tree) == []

    def test_jsx_text_is_checked(self, tree: Path) -> None:
        write(tree, "frontend/src/features/x.tsx", "const a = <p>Welcome back to your shop</p>;\n")
        assert any("welcome back" in p.lower() for p in problems(tree))

    def test_comments_are_ignored(self, tree: Path) -> None:
        write(
            tree,
            "frontend/src/features/x.ts",
            "// seamless, robust and simply great!\n/* just a block */\nconst a = 1;\n",
        )
        assert problems(tree) == []

    def test_test_files_are_skipped(self, tree: Path) -> None:
        write(tree, "frontend/src/features/x.test.tsx", 'it("says seamless things", () => {});\n')
        assert problems(tree) == []


def test_main_exit_codes(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert checker.main(["--root", str(tree)]) == 0
    assert "passed" in capsys.readouterr().out
    write(tree, "context/x.md", f"a {EM} b\n")
    assert checker.main(["--root", str(tree)]) == 1
    assert "context/x.md:1" in capsys.readouterr().out
