import pytest

from boaviztapi_mcp import __version__
from boaviztapi_mcp.__main__ import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_invalid_environment_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BOAVIZTAPI_TIMEOUT", "never")
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "BOAVIZTAPI_TIMEOUT must be a number" in capsys.readouterr().err
