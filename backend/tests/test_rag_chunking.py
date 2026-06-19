"""
Regression guard for the text splitter.

`_chunk_text` set ``start = end - overlap`` with no forward-progress guarantee.
When a window's only separator sat within ``overlap`` chars of ``start`` (common
in big PDFs/markdown: base64 blobs, wide tables, minified data, CJK runs with no
spaces), ``start`` stopped advancing and the loop appended chunks forever —
pinning one CPU core at 100% and growing an unbounded list until the container
was OOM-killed and restarted (the reported "big upload restarts DokOps" bug).

The buggy version never returns, so we run the splitter in a subprocess that the
parent hard-kills on timeout — an in-process thread can't be killed and its tight
pure-Python loop would starve the test run via the GIL.
"""
import json
import os
import subprocess
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHILD = r"""
import sys, json
from app.services.rag_service import _chunk_text
text = sys.stdin.read()
chunks = _chunk_text(text)
joined = "".join(chunks)
print(json.dumps({
    "n": len(chunks),
    "maxlen": max((len(c) for c in chunks), default=0),
    "joined_len": len(joined),
    "has_x": ("X" * 100) in joined,
    "has_y": ("Y" * 100) in joined,
}))
"""


def _chunk_in_subprocess(text: str, seconds: float = 8.0):
    """Run _chunk_text in an isolated process; return result dict or None if it hung."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD],
            input=text,
            cwd=_BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=seconds,
        )
    except subprocess.TimeoutExpired:
        return None  # infinite loop — process was killed
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    return json.loads(proc.stdout.strip())


def test_chunk_text_terminates_on_long_no_whitespace_runs():
    # 20 lines of ~3000 non-whitespace chars — the shape that stalled the splitter.
    text = ("data:" + "A" * 3000 + "\n") * 20

    result = _chunk_in_subprocess(text)

    assert result is not None, "_chunk_text did not terminate — infinite loop in the splitter"
    stride = 2000 - 200
    assert result["n"] < (len(text) // stride) + 50, (
        f"produced {result['n']} chunks for {len(text)} chars — splitter is not "
        "advancing one stride at a time."
    )


def test_chunk_text_covers_all_content_with_no_whitespace():
    # Every region must still be represented (no silent data loss after the fix).
    text = "X" * 5000 + "\n" + "Y" * 5000

    result = _chunk_in_subprocess(text)

    assert result is not None, "_chunk_text did not terminate on a long no-whitespace run"
    assert result["has_x"] and result["has_y"]


def test_chunk_text_normal_prose_unchanged():
    # Normal prose must keep chunking sensibly (no regression for the common path).
    text = "The quick brown fox jumps over the lazy dog. " * 500

    result = _chunk_in_subprocess(text)

    assert result is not None
    assert result["maxlen"] <= 2200  # ~chunk_size, allowing separator slack
    assert result["n"] >= 5
