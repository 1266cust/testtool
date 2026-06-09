import pytest
from pathlib import Path
from test_tool.parsers.text_parser import read_text_file
from test_tool.parsers.csv_parser import read_csv_file
from test_tool.parsers.json_parser import read_json_file


class TestTextParser:
    def test_read_text_file(self, tmp_path: Path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello World\n这是测试", encoding="utf-8")

        content = read_text_file(file_path)
        assert content == "Hello World\n这是测试"


class TestCSVParser:
    def test_read_csv_file(self, tmp_path: Path):
        file_path = tmp_path / "test.csv"
        file_path.write_text("列A,列B,列C\n值1,值2,值3\n值4,值5,值6", encoding="utf-8-sig")

        content = read_csv_file(file_path)
        assert "列A | 列B | 列C" in content
        assert "值1 | 值2 | 值3" in content


class TestJSONParser:
    def test_read_json_file(self, tmp_path: Path):
        file_path = tmp_path / "test.json"
        file_path.write_text('{"key": "value", "number": 123}', encoding="utf-8")

        content = read_json_file(file_path)
        assert '"key"' in content
        assert '"value"' in content
        assert '"number"' in content