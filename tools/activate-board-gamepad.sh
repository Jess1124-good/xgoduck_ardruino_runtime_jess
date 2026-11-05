#!/usr/bin/env bash
# Run in a normal UNO Q host terminal. Selects this App and enables boot services.
set -euo pipefail
app_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
controller_mac=47:84:65:FD:BE:E7
expected_walk=5727b909d5ea1a0f9ff63bf4cea9707339dea6a522374c7a120da633605b923f
cd "$app_root"

python3 - "$app_root" "$expected_walk" <<'PY'
import ast
import hashlib
from pathlib import Path
import sys

root, expected = Path(sys.argv[1]), sys.argv[2]
board = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')[0]
if board != b'arduino,imola':
    raise SystemExit('Expected an UNO Q; stopping before changing any App.')
model = root / 'python/xgoduck_walk.onnx'
actual = hashlib.sha256(model.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit('walk.onnx differs from the verified master copy; stopping before changing any App.')
for rel in ('python/controller.py', 'python/main.py', 'tools/board-gamepad.py', 'tools/switch-to-master.py'):
    ast.parse((root / rel).read_text(), filename=rel)
if "'/api/gamepad'" not in (root / 'python/main.py').read_text():
    raise SystemExit('This App does not contain the board-gamepad API.')
print('Verified master walk.onnx:', actual, flush=True)
PY

router_start="$(systemctl show arduino-router -p ExecStart --value)"
if [[ "$router_start" != *'--serial-baudrate 2000000'* && "$router_start" != *'--serial-baudrate=2000000'* ]]; then
    printf '%s\n' 'Router is not configured for this App at 2 Mbps; no App was changed.' >&2
    exit 1
fi

# Check privilege availability before stopping the old App.
sudo -v
setup_backup="$app_root/data/gamepad-setup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$setup_backup"
arduino-app-cli properties get default > "$setup_backup/default-before.txt"
arduino-app-cli app ps --all > "$setup_backup/apps-before.txt"
if sudo test -f /etc/systemd/system/board-gamepad.service; then
    sudo cat /etc/systemd/system/board-gamepad.service > "$setup_backup/board-gamepad.service.before"
fi

# Stop any existing host reader before reloading the App it controls.
if systemctl is-active --quiet board-gamepad.service; then
    sudo systemctl stop board-gamepad.service
fi
python3 tools/switch-to-master.py
arduino-app-cli app logs "$app_root" --tail 30

python3 - "$app_root" "$expected_walk" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline = time.monotonic() + 45
reason = 'App has not responded yet'
while time.monotonic() < deadline:
    try:
        with http.open('http://127.0.0.1:9527/api/status', timeout=2) as response:
            status = json.load(response)
        startup = status.get('startup_pose', {})
        if status.get('mode') not in ('shadow', 'hold') or (
                status.get('mode') == 'hold' and not startup.get('active')):
            raise SystemExit('App left automatic startup pose. Boot-service setup was not continued.')
        ready = (status.get('board_gamepad_protocol') == 1
                 and status.get('mode') == 'hold' and startup.get('active')
                 and status.get('enabled') and startup.get('zeros_confirmed')
                 and status.get('control_ready')
                 and len(status.get('servo_ids', [])) == 15
                 and status.get('feedback_hz', 0) > 50)
        if ready:
            actual = hashlib.sha256((Path(sys.argv[1]) / 'python/xgoduck_walk.onnx').read_bytes()).hexdigest()
            if actual != sys.argv[2]:
                raise SystemExit('walk.onnx changed during launch; stopping boot-service setup.')
            fields = ('mode', 'enabled', 'feedback_hz', 'inference_hz', 'servo_ids',
                      'imu_ok', 'board_gamepad_protocol', 'input_source', 'startup_pose', 'last_error')
            print(json.dumps({key: status.get(key) for key in fields}, ensure_ascii=False, indent=2))
            break
        reason = json.dumps({key: status.get(key) for key in (
            'mode', 'enabled', 'startup_pose', 'board_gamepad_protocol', 'control_ready', 'servo_ids', 'imu_ok', 'last_error')})
    except (OSError, ValueError) as exc:
        reason = str(exc)
    time.sleep(1)
else:
    raise SystemExit('Master App did not become ready. Boot-service setup was not continued. ' + reason)
PY

printf '%s\n' 'Checking live App logs for 5 seconds.'
log_status=0
timeout --signal=INT --kill-after=2s 5s arduino-app-cli app logs "$app_root" --tail 10 --follow || log_status=$?
if [[ "$log_status" != 0 && "$log_status" != 124 && "$log_status" != 137 ]]; then
    printf 'Could not read App logs (exit %s); boot-service setup was not continued.\n' "$log_status" >&2
    exit 1
fi

# Only the user's already paired controller is trusted; no scanning or new pairing.
controller_info="$(LC_ALL=C bluetoothctl --timeout 8 info "$controller_mac")"
if [[ "$controller_info" != *'Paired: yes'* ]]; then
    printf '%s\n' 'Controller is not paired. Pair it before enabling the boot service.' >&2
    exit 1
fi
LC_ALL=C bluetoothctl --timeout 8 trust "$controller_mac"
controller_info="$(LC_ALL=C bluetoothctl --timeout 8 info "$controller_mac")"
if [[ "$controller_info" != *'Trusted: yes'* ]]; then
    printf '%s\n' 'Controller trust was not saved; boot-service setup was not continued.' >&2
    exit 1
fi

arduino-app-cli properties set default "$app_root"
sudo install -m 644 tools/board-gamepad.service /etc/systemd/system/board-gamepad.service
sudo systemctl daemon-reload
sudo systemctl enable board-gamepad.service
sudo systemctl restart board-gamepad.service
systemctl is-active --quiet board-gamepad.service
printf '%s\n' 'Master App and gamepad boot service are configured. Default pose is enabled; walking waits for A.'
arduino-app-cli app ps
arduino-app-cli properties get default
journalctl -u board-gamepad.service -n 12 --no-pager
printf '%s\n' 'Default pose holds without the browser or gamepad. Center sticks and release LB, then A to walk; B turns torque off.'
printf 'Previous setup saved at: %s\n' "$setup_backup"
