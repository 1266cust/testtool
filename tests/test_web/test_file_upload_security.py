import pytest
from unittest.mock import Mock
from pathlib import Path

from test_tool.web import validate_upload_file, ALLOWED_EXTENSIONS_WEB, _safe_name


class TestFileUploadSecurity:
    def test_allowed_extensions(self):
        allowed = ['.txt', '.pdf', '.docx', '.png', '.xlsx', '.csv', '.json', '.md', '.jpg', '.jpeg']
        for ext in allowed:
            mock_file = Mock()
            mock_file.filename = f"test{ext}"
            mock_file.content_type = "application/octet-stream"

            is_valid, _ = validate_upload_file(mock_file)
            assert is_valid, f"Extension {ext} should be allowed"

    def test_blocked_extensions(self):
        dangerous_exts = ['.exe', '.bat', '.sh', '.py', '.php', '.js', '.html', '.dll', '.msi']

        for ext in dangerous_exts:
            mock_file = Mock()
            mock_file.filename = f"malicious{ext}"
            mock_file.content_type = "application/octet-stream"

            is_valid, error = validate_upload_file(mock_file)
            assert not is_valid, f"Extension {ext} should be blocked"
            assert "不允许" in error

    def test_empty_filename(self):
        mock_file = Mock()
        mock_file.filename = ""
        mock_file.content_type = "text/plain"

        is_valid, error = validate_upload_file(mock_file)
        assert not is_valid
        assert "未提供文件" in error

    def test_path_traversal_prevention(self):
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "/etc/passwd",
            "~/secret.txt",
        ]

        for path in dangerous_paths:
            safe = _safe_name(path)
            assert ".." not in safe
            assert "/" not in safe
            assert "\\" not in safe

    def test_safe_name_preserves_filename(self):
        safe = _safe_name("test_document.pdf")
        assert safe == "test_document.pdf"

        safe = _safe_name("/uploads/test.txt")
        assert safe == "test.txt"

    def test_no_file_object(self):
        is_valid, error = validate_upload_file(None)
        assert not is_valid
        assert "未提供文件" in error