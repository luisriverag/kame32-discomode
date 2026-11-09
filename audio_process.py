"""Bounded analysis admission and process lifetime, independent of robot dispatch."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

_SLOT = threading.BoundedSemaphore(1)


class AnalysisBusy(Exception):
    pass


class AnalysisTimeout(Exception):
    pass


def analyze_in_process(path, timeout=180):
    if not _SLOT.acquire(blocking=False):
        raise AnalysisBusy()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('audio_worker.py')), path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AnalysisTimeout() from None
        if process.returncode:
            raise ValueError('Audio worker failed or exceeded its resource budget.')
        result = json.loads(output)
        return result['events'], result['tempo'], result['duration']
    finally:
        # Also terminate any decoder descendants, even if the worker exited first.
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        _SLOT.release()
