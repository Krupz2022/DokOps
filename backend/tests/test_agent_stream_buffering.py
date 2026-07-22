"""A streamed command must deliver output as it is produced, not in 4KB lumps.

bufsize=1 only governs the parent's reads; a Python child writing to a pipe
block-buffers unless PYTHONUNBUFFERED is set. These tests exercise a real child
process rather than asserting on the env dict, so they fail if the mechanism
stops working for any reason — not just if the variable goes missing.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import blueprint as h  # noqa: E402


# Child prints three lines with a pause between them, then exits. A block-buffered
# child delivers all three at the end; a line-buffered one delivers each on time.
CHILD = (
    "import sys,time\n"
    "for i in range(3):\n"
    "    print('line%d' % i)\n"
    "    time.sleep(0.35)\n"
)


def _collect(monkeypatch):
    """Run the child through _run's streaming path, timestamping each emitted line."""
    seen: list[tuple[float, str]] = []
    start = time.perf_counter()

    token = h._emit_var.set(lambda ev: seen.append((time.perf_counter() - start, ev["line"])))
    rid = h._rid_var.set("r1")
    try:
        rc, out = h._run([sys.executable, "-c", CHILD])
    finally:
        h._emit_var.reset(token)
        h._rid_var.reset(rid)
    return rc, [line for _, line in seen], [t for t, _ in seen]


def test_streamed_lines_arrive_incrementally(monkeypatch):
    rc, lines, times = _collect(monkeypatch)
    assert rc == 0
    assert lines == ["line0", "line1", "line2"]

    # The first line must land well before the process finishes. With block
    # buffering every timestamp collapses to the end (~1.05s).
    assert times[0] < 0.30, f"first line arrived at {times[0]:.2f}s — output was buffered"
    assert times[-1] - times[0] > 0.4, (
        f"all lines arrived within {times[-1] - times[0]:.2f}s — they came as one flush"
    )


import pytest  # noqa: E402


# ── PTY output rendering (pure, runs on every platform) ──────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("plain line", "plain line"),
    ("with crlf\r", "with crlf"),                              # PTY ends lines \r\n
    ("\x1b[32mok:\x1b[0m [host]", "ok: [host]"),               # colour stripped
    ("Extract 10%\rExtract 50%\rExtract 90%", "Extract 90%"),  # only final redraw
    ("Extract 50%\rExtract 90%\r", "Extract 90%"),             # redraw + trailing CR
    ("\x1b]0;title\x07done", "done"),                          # OSC stripped
    ("", ""),
])
def test_clean_line_renders_like_a_terminal(raw, expected):
    assert h._clean_line(raw) == expected


# ── PTY streaming (POSIX only — no pty module on Windows) ────────────────────

NONPYTHON_CHILD = "for i in 0 1 2; do echo line$i; sleep 0.35; done"


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only; Windows uses the pipe path")
def test_pty_streams_shell_command_incrementally():
    """A shell/C program must stream too — that's the case PYTHONUNBUFFERED misses."""
    seen: list[tuple[float, str]] = []
    start = time.perf_counter()

    token = h._emit_var.set(lambda ev: seen.append((time.perf_counter() - start, ev["line"])))
    rid = h._rid_var.set("r1")
    try:
        rc, _ = h._run(NONPYTHON_CHILD, shell=True)
    finally:
        h._emit_var.reset(token)
        h._rid_var.reset(rid)

    assert rc == 0
    assert [line for _, line in seen] == ["line0", "line1", "line2"]
    first = seen[0][0]
    assert first < 0.30, f"first line arrived at {first:.2f}s — output was buffered"


def test_stream_env_preserves_existing_environment():
    env = h._stream_env()
    assert env["PYTHONUNBUFFERED"] == "1"
    # Must not replace the child's environment — PATH and friends have to survive,
    # or commands stop resolving on the minion.
    for key in list(os.environ)[:5]:
        assert key in env
