import signal
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "resume_stopped.sh"


def _stat(pid: int) -> str:
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()


def _child_of(pid: int) -> int:
    for _ in range(50):
        out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
        if out:
            return int(out[0])
        time.sleep(0.05)
    raise AssertionError("child never appeared")


def test_resumes_stopped_child_once():
    root = subprocess.Popen(["bash", "-c", "sleep 30; true"])
    try:
        child = _child_of(root.pid)
        subprocess.run(["kill", "-STOP", str(child)], check=True)
        time.sleep(0.1)
        assert _stat(child).startswith("T")

        out = subprocess.run(["bash", str(SCRIPT), str(root.pid)], capture_output=True, text=True, check=True).stdout
        assert out.split()[0] == str(child)
        assert len(out.strip().splitlines()) == 1
        assert not _stat(child).startswith("T")

        again = subprocess.run(["bash", str(SCRIPT), str(root.pid)], capture_output=True, text=True, check=True).stdout
        assert again == ""
    finally:
        root.send_signal(signal.SIGKILL)
        subprocess.run(["pkill", "-P", str(root.pid)])
        root.wait()
