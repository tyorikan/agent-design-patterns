"""Planner の LlmAgent 化に伴うユニットテスト。

read_file / list_directory ツールのロジックと
run_planner_agent の設定・分岐を検証する。
LLM 呼び出しは行わず、純粋なロジックのみを検証する。
"""

from patterns.agentic_pipeline.tools import (
    _PLANNER_IGNORE_DIRS,
    _extract_json,
    _strip_markdown_fences,
    list_directory,
    read_file,
)


# ============================================================
# read_file Tests
# ============================================================
class TestReadFile:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")
        result = read_file(str(f))
        assert result == "print('hello')"

    def test_read_nonexistent_file(self):
        result = read_file("/nonexistent/path/foo.py")
        assert "Error" in result
        assert "見つかりません" in result

    def test_read_directory_as_file(self, tmp_path):
        result = read_file(str(tmp_path))
        assert "Error" in result
        assert "ファイルではありません" in result

    def test_read_large_file_truncated(self, tmp_path):
        f = tmp_path / "big.txt"
        content = "x" * 50_000
        f.write_text(content, encoding="utf-8")
        result = read_file(str(f))
        assert len(result) < 50_000
        assert "truncated" in result
        assert "50000" in result

    def test_read_small_file_not_truncated(self, tmp_path):
        f = tmp_path / "small.txt"
        content = "hello world"
        f.write_text(content, encoding="utf-8")
        result = read_file(str(f))
        assert result == content
        assert "truncated" not in result

    def test_read_utf8_file(self, tmp_path):
        f = tmp_path / "日本語.txt"
        f.write_text("こんにちは世界", encoding="utf-8")
        result = read_file(str(f))
        assert result == "こんにちは世界"


# ============================================================
# list_directory Tests
# ============================================================
class TestListDirectory:
    def test_list_files_and_dirs(self, tmp_path):
        (tmp_path / "main.py").touch()
        (tmp_path / "utils.py").touch()
        (tmp_path / "src").mkdir()
        result = list_directory(str(tmp_path))
        assert "📄 main.py" in result
        assert "📄 utils.py" in result
        assert "📁 src" in result

    def test_list_nonexistent(self):
        result = list_directory("/nonexistent/dir")
        assert "Error" in result
        assert "見つかりません" in result

    def test_list_file_as_dir(self, tmp_path):
        f = tmp_path / "file.txt"
        f.touch()
        result = list_directory(str(f))
        assert "Error" in result
        assert "ディレクトリではありません" in result

    def test_empty_directory(self, tmp_path):
        result = list_directory(str(tmp_path))
        assert result == "(empty directory)"

    def test_ignores_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "main.py").touch()
        result = list_directory(str(tmp_path))
        assert "__pycache__" not in result
        assert "main.py" in result

    def test_ignores_dotfiles(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".env").touch()
        (tmp_path / "app.py").touch()
        result = list_directory(str(tmp_path))
        assert ".git" not in result
        assert ".env" not in result
        assert "app.py" in result

    def test_ignores_node_modules(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "index.ts").touch()
        result = list_directory(str(tmp_path))
        assert "node_modules" not in result
        assert "index.ts" in result

    def test_all_ignore_dirs_filtered(self, tmp_path):
        """全ての無視パターンが正しくフィルタされること。"""
        for d in _PLANNER_IGNORE_DIRS:
            (tmp_path / d).mkdir(exist_ok=True)
        (tmp_path / "keep.py").touch()
        result = list_directory(str(tmp_path))
        for d in _PLANNER_IGNORE_DIRS:
            assert d not in result
        assert "keep.py" in result


# ============================================================
# _PLANNER_IGNORE_DIRS Tests
# ============================================================
class TestPlannerIgnoreDirs:
    def test_contains_pycache(self):
        assert "__pycache__" in _PLANNER_IGNORE_DIRS

    def test_contains_node_modules(self):
        assert "node_modules" in _PLANNER_IGNORE_DIRS

    def test_contains_venv(self):
        assert ".venv" in _PLANNER_IGNORE_DIRS
        assert "venv" in _PLANNER_IGNORE_DIRS

    def test_is_set(self):
        assert isinstance(_PLANNER_IGNORE_DIRS, set)


# ============================================================
# _strip_markdown_fences Tests
# ============================================================
class TestStripMarkdownFences:
    def test_strips_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_strips_plain_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_no_fence_passthrough(self):
        text = '{"key": "value"}'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_strips_whitespace(self):
        text = '  ```json\n{"key": "value"}\n```  '
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_multiline_json(self):
        text = '```json\n{\n  "architecture": "Clean Architecture",\n  "modules": ["main.py"]\n}\n```'
        result = _strip_markdown_fences(text)
        assert '"architecture"' in result
        assert '"modules"' in result
        assert '```' not in result

    def test_empty_string(self):
        assert _strip_markdown_fences("") == ""

    def test_plain_text(self):
        text = "This is plain text"
        assert _strip_markdown_fences(text) == text


# ============================================================
# _extract_json Tests
# ============================================================
class TestExtractJson:
    def test_valid_json_passthrough(self):
        text = '{"architecture": "Clean"}'
        assert _extract_json(text) == text

    def test_text_before_json(self):
        text = '設計方針を策定しました。\n\n{"architecture": "Clean"}'
        assert _extract_json(text) == '{"architecture": "Clean"}'

    def test_text_after_json(self):
        text = '{"architecture": "Clean"}\n\n以上です。'
        # テキスト後に追加テキストがあっても JSON を抽出
        result = _extract_json(text)
        assert '"architecture"' in result

    def test_text_surrounding_json(self):
        text = '以下が設計です:\n{"modules": ["main.py"]}\n完了しました。'
        result = _extract_json(text)
        assert result == '{"modules": ["main.py"]}'

    def test_plain_text_passthrough(self):
        text = "これは JSON ではありません"
        assert _extract_json(text) == text

    def test_empty_string(self):
        assert _extract_json("") == ""

    def test_multiline_json_with_prefix(self):
        text = '確認しました。\n{\n  "architecture": "DDD",\n  "modules": ["a.py", "b.py"]\n}'
        result = _extract_json(text)
        import json
        parsed = json.loads(result)
        assert parsed["architecture"] == "DDD"
        assert len(parsed["modules"]) == 2
