"""Regression checks for the Windows one-click server launcher."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "启动服务器.bat"


def test_launcher_prefers_project_venv_and_reuses_resolved_interpreter():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert r"%PROJECT_DIR%\.venv\Scripts\python.exe" in source
    assert 'set "PYTHON_EXE=' in source
    assert '"%PYTHON_EXE%" %PYTHON_ARGS% --version' in source
    assert '"%PYTHON_EXE%" %PYTHON_ARGS% -m uvicorn' in source


def test_launcher_installs_missing_dependencies_into_project_venv():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert '-c "import pyarrow"' in source
    assert '-c "import scipy"' in source
    assert '-c "import sklearn"' in source
    assert '-c "import yfinance"' in source
    assert '-c "import akshare"' in source
    assert r'%PYTHON_ARGS% -m venv "%PROJECT_DIR%\.venv"' in source
    assert '"%PYTHON_EXE%" -m pip install -r requirements.txt' in source
