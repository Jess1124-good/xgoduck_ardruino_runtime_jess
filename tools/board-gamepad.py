"""Read a paired joystick on the UNO Q host. Preview by default; --run controls App.

Uses the installed Linux joystick ABI, no extra Python packages required.
Run on the host (SSH/desktop), not inside the Arduino App container.
"""
import argparse
import array
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

EVENT = struct.Struct('=IhBB')
ABS_X, ABS_Y, ABS_Z, ABS_RX = 0, 1, 2, 3
BTN_A, BTN_B, BTN_LB = 0x130, 0x131, 0x136


def ioctl_read(fd, number, size):
    buffer = bytearray(size)
    fcntl.ioctl(fd, 0x80000000 | (size << 16) | (ord('j') << 8) | number, buffer, True)
    return buffer


class Joystick:
    def __init__(self, node, mac):
        self.node = Path(node)
        device = Path('/sys/class/input') / self.node.name / 'device'
        # Bind to the paired device's identity, not a transient js0 number.
        identity = (device / 'uniq').read_text().strip().lower()
        bus = (device / 'id/bustype').read_text().strip()
        if identity != mac.lower() or bus != '0005':
            raise ValueError('joystick does not match the selected Bluetooth MAC')
        self.fd = os.open(self.node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            self.name = ioctl_read(self.fd, 0x13, 128).split(b'\0', 1)[0].decode(errors='replace')
            naxes = ioctl_read(self.fd, 0x11, 1)[0]
            nbuttons = ioctl_read(self.fd, 0x12, 1)[0]
            self.axis_map = list(ioctl_read(self.fd, 0x32, 64))[:naxes]
            button_map = array.array('H', ioctl_read(self.fd, 0x34, 1024))
            self.button_map = list(button_map)[:nbuttons]
            # Bluetooth Xbox descriptors use either RX or Z for right-stick X.
            self.yaw_axis = ABS_RX if ABS_RX in self.axis_map else ABS_Z
            if not {ABS_X, ABS_Y, self.yaw_axis} <= set(self.axis_map) or not {
                    BTN_A, BTN_B, BTN_LB} <= set(self.button_map):
                raise ValueError('required stick axes or A/B/LB buttons are missing')
            self.axes, self.buttons = {}, {}
        except Exception:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self):
        button_events = []
        while True:
            try:
                data = os.read(self.fd, EVENT.size * 64)
            except BlockingIOError:
                break
            if not data or len(data) % EVENT.size:
                raise OSError('joystick disconnected or invalid event stream')
            for _, value, kind, number in EVENT.iter_unpack(data):
                initial = bool(kind & 0x80)
                kind &= ~0x80  # Initial-state events use the same axis/button map.
                if kind == 2 and number < len(self.axis_map):
                    self.axes[self.axis_map[number]] = max(-1.0, min(1.0, value / 32767.0))
                elif kind == 1 and number < len(self.button_map):
                    code = self.button_map[number]
                    self.buttons[code] = bool(value)
                    if not initial:
                        button_events.append({'code': code, 'pressed': bool(value)})
        initialized = ({ABS_X, ABS_Y, self.yaw_axis} <= self.axes.keys()
                       and {BTN_A, BTN_B, BTN_LB} <= self.buttons.keys())
        return dict(axes=[self.axes.get(code, 0.0) for code in (ABS_X, ABS_Y, self.yaw_axis)],
                    a=self.buttons.get(BTN_A, False), b=self.buttons.get(BTN_B, False),
                    lb=self.buttons.get(BTN_LB, False), initialized=initialized,
                    button_events=button_events)


class InputGate:
    def __init__(self, speed=0.5):
        self.speed = speed
        self.ready = self.a_down = False

    def reset(self):
        # Do not retrigger an A button that is still held after a failed request.
        self.ready = False

    def sample(self, state):
        a, b, lb = state['a'], state['b'], state['lb']
        presses = {event['code'] for event in state.get('button_events', []) if event['pressed']}
        releases = {event['code'] for event in state.get('button_events', []) if not event['pressed']}
        rising = (a and not self.a_down) or BTN_A in presses
        self.a_down = a
        b = b or BTN_B in presses
        if not state['initialized'] or b or not all(math.isfinite(v) for v in state['axes']):
            self.reset()
            return dict(start=False, stop=b, twist=[0.0]*3, ready=False)
        centered = all(abs(v) <= 0.12 for v in state['axes'])
        if not self.ready:
            self.ready = centered and not (a or b or lb)
        start = self.ready and rising and centered and not lb and BTN_LB not in presses
        def axis(value):
            value = max(-1.0, min(1.0, value))
            return 0.0 if abs(value) <= .12 else math.copysign((abs(value)-.12)/.88, value)
        x, y, yaw = [axis(v) for v in state['axes']]
        twist = [-y*.4*self.speed, -x*.3*self.speed, -yaw*self.speed] if self.ready and lb and BTN_LB not in releases else [0.0]*3
        return dict(start=start, stop=False, twist=twist, ready=self.ready)


class PreviewSummary:
    def __init__(self):
        self.axis_ranges = None
        self.buttons = set()
        self.motion = self.start = self.stop = False

    def observe(self, state, mapped):
        if state['initialized']:
            if self.axis_ranges is None:
                self.axis_ranges = [[value, value] for value in state['axes']]
            else:
                for bounds, value in zip(self.axis_ranges, state['axes']):
                    bounds[0], bounds[1] = min(bounds[0], value), max(bounds[1], value)
        names = {BTN_A: 'A', BTN_B: 'B', BTN_LB: 'LB'}
        for code, name in names.items():
            if state[name.lower()]:
                self.buttons.add(name)
        for event in state.get('button_events', []):
            if event['pressed'] and event['code'] in names:
                self.buttons.add(names[event['code']])
        self.motion |= any(mapped['twist'])
        self.start |= mapped['start']
        self.stop |= mapped['stop']

    def report(self):
        return dict(observed_buttons=sorted(self.buttons),
                    axis_ranges=dict(zip(('left_x', 'left_y', 'right_x'), self.axis_ranges))
                        if self.axis_ranges is not None else {},
                    motion_observed=self.motion, start_observed=self.start, stop_observed=self.stop)


class Client:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.path not in ('', '/'):
            raise ValueError('App URL must be HTTP on this board\'s localhost')
        self.url, self.session, self.seq = url.rstrip('/'), None, 0
        # Read joystick input only on the host; never use an environment HTTP proxy.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, body=None):
        req = urllib.request.Request(self.url + '/api/' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            with self.http.open(req, timeout=.15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode(errors='replace')
            raise ValueError('App rejected gamepad input: ' + detail) from exc

    def send(self, action, twist=None, device=''):
        self.seq += 1
        return self.request('gamepad', dict(action=action, session=self.session,
            seq=self.seq, twist=twist or [0.0]*3, device=device, sent_at=time.monotonic()))

    def start(self, device):
        status = self.request('status')
        if status.get('board_gamepad_protocol') != 1:
            raise ValueError('Running App has no board-gamepad API. Deploy the updated -master App first.')
        reply = self.send('start', device=device)
        self.session = reply['session']

    def release(self):
        if self.session:
            try:
                self.send('release')
            except (OSError, ValueError) as exc:
                print('Release request failed; App gamepad watchdog must stop control:', exc, flush=True)
            finally:
                self.session = None

    def stop(self):
        # Unlike release(), B must also stop startup hold without a walk session.
        try:
            self.send('stop')
        finally:
            self.session = None


def reconnect(mac, stopped, missing):
    """Only reconnect the chosen, already paired and trusted remote device."""
    delay, last_message = 2.0, ''
    while not stopped.wait(delay):
        if not missing.is_set():
            delay = 2.0
            continue
        try:
            info = subprocess.run(['bluetoothctl', '--timeout', '5', 'info', mac],
                                  capture_output=True, text=True, timeout=7)
            if info.returncode != 0:
                raise ValueError('Cannot query paired controller: ' + info.stderr.strip()[:160])
            if 'Paired: yes' not in info.stdout or 'Trusted: yes' not in info.stdout:
                raise ValueError('Auto-reconnect requires this controller to be paired and trusted first')
            if 'Connected: yes' not in info.stdout:
                result = subprocess.run(['bluetoothctl', '--timeout', '5', 'connect', mac],
                                        capture_output=True, text=True, timeout=7)
                if result.returncode != 0:
                    raise ValueError('Reconnect waiting: ' + result.stdout.strip()[-160:])
            last_message = ''
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            if str(exc) != last_message:
                print(str(exc), flush=True)
                last_message = str(exc)
        delay = min(30.0, delay * 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mac', required=True, help='paired controller Bluetooth address')
    parser.add_argument('--device', default='', help='optional /dev/input/jsN; identity is still verified')
    parser.add_argument('--speed', type=float, choices=(.25, .5, 1.0), default=.5)
    parser.add_argument('--url', default='http://127.0.0.1:9527')
    parser.add_argument('--run', action='store_true', help='send control to App; default only prints inputs')
    parser.add_argument('--reconnect', action='store_true', help='retry Bluetooth connection to this already paired/trusted controller')
    parser.add_argument('--seconds', type=float, default=0, help='exit after this many seconds (0: until Ctrl-C)')
    args = parser.parse_args()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', args.mac):
        parser.error('--mac must be a Bluetooth address such as 47:84:65:FD:BE:E7')
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    client = Client(args.url) if args.run else None
    missing = threading.Event()
    missing.set()
    if args.reconnect:
        threading.Thread(target=reconnect, args=(args.mac, stopped, missing), daemon=True,
                         name='bluetooth-reconnect').start()
    stick, gate = None, InputGate(args.speed)
    started = time.monotonic()
    last_print, last_message = 0.0, ''
    stop_latched = False
    summary = PreviewSummary()
    print('CONTROL: release LB, center sticks, press A to start walking; hold LB to move; B stops torque.'
          if client else 'PREVIEW ONLY: no API calls or motor commands. Move sticks and press A/B/LB.', flush=True)
    try:
        while not stopped.is_set() and (args.seconds <= 0 or time.monotonic()-started < args.seconds):
            tick = time.monotonic()
            try:
                if stick is None:
                    nodes = [Path(args.device)] if args.device else sorted(Path('/dev/input').glob('js*'))
                    for node in nodes:
                        try:
                            stick = Joystick(node, args.mac)
                            break
                        except (OSError, ValueError):
                            continue
                    if stick is None:
                        raise OSError('Waiting for matching joystick; check connection, /dev/input and input-group access')
                    gate = InputGate(args.speed)
                    stop_latched = False
                    print(json.dumps(dict(device=str(stick.node), name=stick.name,
                          axis_map=stick.axis_map, button_map=stick.button_map)), flush=True)
                state = stick.read()
                missing.clear()
                mapped = gate.sample(state)
                if client is None:
                    summary.observe(state, mapped)
                if client:
                    if mapped['stop']:
                        if not stop_latched:
                            client.stop()
                    elif mapped['start'] and not client.session:
                        client.start(stick.name)
                        print('Gamepad controls walking', flush=True)
                    elif client.session:
                        client.send('update', mapped['twist'])
                    stop_latched = mapped['stop']
                if state['button_events'] or mapped['start'] or tick-last_print >= .5:
                    print(json.dumps(dict(**state, **mapped, controlling=bool(client and client.session))), flush=True)
                    last_print = tick
                last_message = ''
            except (OSError, ValueError, KeyError) as exc:
                if client:
                    client.release()
                gate.reset()
                if stick:
                    stick.close()
                    stick = None
                missing.set()
                message = str(exc)
                if message != last_message:
                    print(message, flush=True)
                    last_message = message
                stopped.wait(1.0)
            stopped.wait(max(0.0, .02-(time.monotonic()-tick)))
    finally:
        stopped.set()
        if client:
            client.release()
        if stick:
            stick.close()
        if client is None:
            print(json.dumps({'summary': summary.report()}), flush=True)


if __name__ == '__main__':
    main()
