"""Switch/reload this App using explicit CLI stop, wait and start operations."""
from pathlib import Path
import subprocess
import time

STATES = {'starting', 'running', 'stopping', 'stopped', 'failed'}


def app_states():
    output = subprocess.check_output(
        ['arduino-app-cli', '--format', 'text', 'app', 'ps', '--all'],
        text=True, timeout=15)
    result = {}
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0].startswith(('user:', 'examples:')):
            if len(fields) < 2 or fields[1] not in STATES:
                raise ValueError('Unrecognized App status row: ' + line)
            result[fields[0]] = fields[1]
    if not result and output.strip() and not output.lstrip().startswith('ID'):
        raise ValueError('Unrecognized App status output: ' + output[:500])
    return result


def switch_to_master(root, timeout=45):
    root = Path(root).resolve()
    if root.name != 'xgoduck_runtime_arduino-master':
        raise ValueError('This helper only starts xgoduck_runtime_arduino-master')
    paths = {'user:xgoduck_runtime_arduino': root.parent / 'xgoduck_runtime_arduino',
             'user:xgoduck_runtime_arduino-master': root}

    def check_other(states):
        other = [key for key, state in states.items()
                 if key not in paths and state in ('starting', 'running', 'stopping')]
        if other:
            raise ValueError('Another App is active; refusing to stop an unrelated App: ' + ', '.join(other))

    states = app_states()
    check_other(states)
    for app_id, path in paths.items():
        if states.get(app_id) in ('starting', 'running', 'failed'):
            print('Stopping ' + app_id, flush=True)
            subprocess.run(['arduino-app-cli', 'app', 'stop', str(path)],
                           check=True, timeout=45)
    deadline = time.monotonic() + timeout
    while True:
        states = app_states()
        check_other(states)
        pending = [key for key in paths if states.get(key) not in (None, 'stopped')]
        if not pending:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Apps did not stop; master was not started: ' + ', '.join(pending))
        time.sleep(.5)
    print('Starting ' + str(root), flush=True)
    subprocess.run(['arduino-app-cli', 'app', 'start', str(root)], check=True)


if __name__ == '__main__':
    try:
        switch_to_master(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
