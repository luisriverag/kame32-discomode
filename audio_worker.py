"""One-shot audio worker; resource limits apply before importing scientific libraries."""
import json
import os
import resource
import sys

# Linux deployment limits. A fresh process contains native decoder/compiler failures.
resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
os.environ['OPENBLAS_NUM_THREADS'] = '2'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['NUMBA_NUM_THREADS'] = '2'

if __name__ == '__main__':
    from app import build_events
    events, tempo, duration = build_events(sys.argv[1])
    json.dump({'events': events, 'tempo': tempo, 'duration': duration}, sys.stdout)
