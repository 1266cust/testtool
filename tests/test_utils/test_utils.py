import pytest
from pathlib import Path
from test_tool.utils.file_utils import (
    is_supported_file,
    is_image_file,
    get_file_category,
    SUPPORTED_EXTENSIONS,
    IMAGE_EXTENSIONS,
)


class TestFileUtils:
    def test_supported_extensions_set(self):
        expected = {
            ".txt", ".md", ".markdown",
            ".docx", ".pdf",
            ".csv", ".xlsx", ".xlsm",
            ".json",
            ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff",
        }
        assert SUPPORTED_EXTENSIONS == expected

    def test_image_extensions_set(self):
        expected = {
            ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff",
        }
        assert IMAGE_EXTENSIONS == expected

    def test_is_supported_file_txt(self):
        path = Path("test.txt")
        assert is_supported_file(path) is True

    def test_is_supported_file_pdf(self):
        path = Path("document.pdf")
        assert is_supported_file(path) is True

    def test_is_supported_file_exe(self):
        path = Path("program.exe")
        assert is_supported_file(path) is False

    def test_is_supported_file_unknown(self):
        path = Path("data.xyz")
        assert is_supported_file(path) is False

    def test_is_image_file_png(self):
        path = Path("screenshot.png")
        assert is_image_file(path) is True

    def test_is_image_file_jpg(self):
        path = Path("photo.jpg")
        assert is_image_file(path) is True

    def test_is_image_file_pdf(self):
        path = Path("document.pdf")
        assert is_image_file(path) is False

    def test_is_image_file_txt(self):
        path = Path("notes.txt")
        assert is_image_file(path) is False

    def test_get_file_category_image(self):
        assert get_file_category(Path("test.png")) == "image"
        assert get_file_category(Path("photo.jpg")) == "image"
        assert get_file_category(Path("screen.jpeg")) == "image"

    def test_get_file_category_pdf(self):
        assert get_file_category(Path("doc.pdf")) == "pdf"

    def test_get_file_category_text(self):
        assert get_file_category(Path("notes.txt")) == "text"
        assert get_file_category(Path("readme.md")) == "text"
        assert get_file_category(Path("guide.markdown")) == "text"

    def test_get_file_category_docx(self):
        assert get_file_category(Path("report.docx")) == "docx"

    def test_get_file_category_csv(self):
        assert get_file_category(Path("data.csv")) == "csv"

    def test_get_file_category_excel(self):
        assert get_file_category(Path("sheet.xlsx")) == "excel"
        assert get_file_category(Path("macro.xlsm")) == "excel"

    def test_get_file_category_json(self):
        assert get_file_category(Path("config.json")) == "json"

    def test_get_file_category_unknown(self):
        assert get_file_category(Path("file.xyz")) == "unknown"


class TestTextUtils:
    def test_clean_feature_line_bullet(self):
        from test_tool.utils.text_utils import clean_feature_line
        assert clean_feature_line("- 测试功能") == "测试功能"
        assert clean_feature_line("* 功能点") == "功能点"

    def test_clean_feature_line_numbered(self):
        from test_tool.utils.text_utils import clean_feature_line
        assert clean_feature_line("1. 第一项") == "第一项"
        assert clean_feature_line("2. 第二项") == "第二项"

    def test_clean_feature_line_plain(self):
        from test_tool.utils.text_utils import clean_feature_line
        assert clean_feature_line("普通文本") == "普通文本"

    def test_short_text_within_limit(self):
        from test_tool.utils.text_utils import short_text
        assert short_text("短文本", max_len=10) == "短文本"

    def test_short_text_exceeds_limit(self):
        from test_tool.utils.text_utils import short_text
        long = "这是一个非常长的文本内容需要被截断处理"
        result = short_text(long, max_len=10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_split_points(self):
        from test_tool.utils.text_utils import split_points
        text = "功能A；功能B；功能C。功能D"
        points = split_points(text)
        assert len(points) >= 4
        assert "功能A" in points or any("功能A" in p for p in points)