import subprocess
import sys


def test_cancel_kills_process(leike):
    app = leike["App"]()
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        app.export_proc = p
        app._cancelled = False
        app.cancel_export()
        assert app._cancelled is True
        p.wait(timeout=5)
        assert p.returncode is not None      # the process was killed
    finally:
        if p.poll() is None:
            p.kill()
        app.destroy()
