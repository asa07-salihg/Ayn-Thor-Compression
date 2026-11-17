"""The folder picker must keep handhelds that have no drive letter."""

from aynthor.core.win_folder import (
    FOS_FILEMUSTEXIST,
    FOS_FORCEFILESYSTEM,
    FOS_PATHMUSTEXIST,
    FOS_PICKFOLDERS,
    folder_options,
)


def test_the_module_imports_on_linux():
    """Linux CI imports this file. ctypes.HRESULT and windll exist only on Windows."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/aynthor/core/win_folder.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "ctypes":
            names = {alias.name for alias in node.names}
            assert "HRESULT" not in names
            assert "windll" not in names


def test_folder_dialog_accepts_a_handheld_folder():
    options = folder_options(FOS_FORCEFILESYSTEM | FOS_FILEMUSTEXIST | FOS_PATHMUSTEXIST)
    assert options & FOS_PICKFOLDERS
    assert not options & FOS_FORCEFILESYSTEM
    assert not options & FOS_FILEMUSTEXIST
    assert not options & FOS_PATHMUSTEXIST
