import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows byte-range locking regression')
def test_empty_lock_contended_by_another_process_reports_busy(tmp_path):
    import msvcrt

    path = tmp_path / 'empty.lock'
    env = {name: os.environ[name] for name in ('SYSTEMROOT', 'WINDIR', 'PATH') if name in os.environ}
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    script = '''
import sys
from pathlib import Path
from src.model_platforms.security import file_lock, PlatformError
try:
    with file_lock(Path(sys.argv[1]), timeout=0):
        print('acquired')
except PlatformError as exc:
    print(exc.code)
'''
    with path.open('w+b') as holder:
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            result = subprocess.run(
                [sys.executable, '-c', script, str(path)], env=env,
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == 'CONFIG_BUSY'
            assert path.stat().st_size == 0
        finally:
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)

    result = subprocess.run(
        [sys.executable, '-c', script, str(path)], env=env,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'acquired'
    assert path.read_bytes() == b'0'
