from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import pytest

from pudb.debugger import CONFIG, Debugger, DebuggerUI
from pudb.source_view import SourceLine


if TYPE_CHECKING:
    from collections.abc import Callable


def test_hidden_cmdline_does_not_take_focus(monkeypatch, tmp_path):
    monkeypatch.setitem(CONFIG, "hide_cmdline_win", True)
    monkeypatch.setitem(CONFIG, "hotkeys_toggle_cmdline_focus", "ctrl x")
    monkeypatch.setattr("pudb.debugger.get_save_config_path", lambda: str(tmp_path))
    size = (80, 24)
    ui = DebuggerUI(Mock(spec=Debugger), StringIO(), StringIO(), size)
    ui.source[:] = [SourceLine(ui, "pass")]

    ui.top.keypress(size, "down")
    assert ui.lhs_col.focus is ui.source_attr

    ui.top.keypress(size, "ctrl x")
    assert ui.lhs_col.focus is ui.cmdline_sigwrap
    assert ui.cmdline_on

    ui.top.keypress(size, "ctrl x")
    ui.top.keypress(size, "down")
    assert ui.lhs_col.focus is ui.source_attr
    assert not ui.cmdline_on


RECURSIVE_SOURCE = """\
def recurse(depth):
    if depth:
        recurse(depth - 1)
    return depth


after = 1
"""


def press_run_to_frame_line(
            monkeypatch: pytest.MonkeyPatch,
            tmp_path: Path,
            target_lineno: int,
        ) -> tuple[list[tuple[int, int]], list[str]]:
    """Run ``recurse(2)``, press ``T`` on *target_lineno* at the first stop and
    return the ``(depth, lineno)`` stops and the messages shown."""
    for module in ("pudb.debugger", "pudb.settings"):
        monkeypatch.setattr(f"{module}.get_save_config_path", lambda: str(tmp_path))

    script = tmp_path / "recursive.py"
    script.write_text(RECURSIVE_SOURCE)
    namespace: dict[str, Any] = {}
    exec(compile(RECURSIVE_SOURCE, str(script), "exec"), namespace)

    size = (80, 24)
    dbg = Debugger(stdin=StringIO(), stdout=StringIO(), term_size=size)
    stops: list[tuple[int, int]] = []
    messages: list[str] = []

    def record_message(msg: str, *_args: object, **_kwargs: object) -> None:
        messages.append(msg)

    def scripted_ui(*_args: object, **_kwargs: object) -> None:
        dbg.ui.quit_event_loop = False
        frame = dbg.curframe
        stops.append((cast("int", frame.f_locals["depth"]), frame.f_lineno))
        if len(stops) == 1:
            dbg.ui.source_list.focus_position = target_lineno - 1
            dbg.ui.source_sigwrap.keypress(size, "T")
        if not dbg.ui.quit_event_loop:
            dbg.set_continue()

    monkeypatch.setattr(dbg.ui, "message", record_message)
    monkeypatch.setattr(dbg.ui, "call_with_ui", scripted_ui)
    try:
        dbg.runcall(cast("Callable[[int], int]", namespace["recurse"]), 2)
    finally:
        dbg.close()
    return stops, messages


def test_run_to_cursor_in_frame_skips_recursive_calls(
            monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stops, messages = press_run_to_frame_line(monkeypatch, tmp_path, 4)

    assert messages == []
    assert stops[:2] == [(2, 2), (2, 4)]


@pytest.mark.parametrize("target_lineno", [
    2,  # the current line
    7,  # outside the current function
])
def test_run_to_cursor_in_frame_rejects_unreachable_line(
            monkeypatch: pytest.MonkeyPatch,
            tmp_path: Path,
            target_lineno: int) -> None:
    stops, messages = press_run_to_frame_line(monkeypatch, tmp_path, target_lineno)

    assert len(messages) == 1
    assert stops == [(2, 2)]
