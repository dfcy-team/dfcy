from pathlib import Path


def test_pilot_wsgi_suppresses_request_line_logging():
    project_root = Path(__file__).resolve().parents[2]
    source = (project_root / "deploy" / "pilot" / "application" / "quiet_wsgi.py").read_text(
        encoding="utf-8"
    )

    assert "class QuietHandler(WSGIRequestHandler)" in source
    assert "def log_message(self, format, *args):" in source
    assert "handler_class=QuietHandler" in source
    assert "runserver" not in source
