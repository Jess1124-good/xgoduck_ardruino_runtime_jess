"""Gamepad input and real Controller tests; fake Bridge, no hardware or HTTP.

Uses the App's installed numpy/onnxruntime if they are not on the host sys.path.
"""
import importlib.util
from dataclasses import replace
from pathlib import Path
import sys
import subprocess
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
if importlib.util.find_spec('numpy') is None:
    cached = ROOT / '.cache/.venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    if cached.is_dir():
        sys.path.insert(0, str(cached))
from controller import Controller, GAMEPAD_TIMEOUT, STARTUP_POSE_SETTLE_S
from rl_core import DEFAULT_DEG
from wire import Feedback, ALL_MASK, COMMAND, DISARM, ARM, HOLD, RAW, STATE

spec = importlib.util.spec_from_file_location('board_gamepad', ROOT / 'tools/board-gamepad.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class FakeBridge:
    def __init__(self):
        self.messages = []

    def notify(self, name, payload):
        self.messages.append((name, payload))


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()
        self.c = Controller(self.bridge)
        self.c.feedback = Feedback(1, ALL_MASK, 1, 10000, 10000, 0, 0, 10000,
                                   3000, 0, 0, 0, (0, 0, -9.8), (0, 0, 0),
                                   tuple(DEFAULT_DEG), (0,)*15, tuple(DEFAULT_DEG))
        self.c.filtered = dict(grav=[0, 0, -1], gyro_rad=[0, 0, 0],
                              angles_deg=DEFAULT_DEG, vels_deg=[0]*15,
                              imu_fusion_ready=True, imu_fusion_updated=True)
        self.c.rx_time = time.monotonic()

    def start(self):
        return self.c.gamepad('start', sent_at=time.monotonic(), device='Xbox Wireless Controller')['session']

    def update(self, session, seq=1, **kwargs):
        return self.c.gamepad('update', session=session, seq=seq, sent_at=time.monotonic(), **kwargs)

    def test_source_arbitration_and_page_exit(self):
        token = self.start()
        self.assertEqual(self.c.mode, 'policy')
        self.update(token, twist=[.2, -.15, .5])
        self.assertTrue(self.c.command(twist=[0, 0, 0])['ignored'])
        self.assertEqual(self.c.twist, [.2, -.15, .5])
        self.c.set_mode('off', page_exit=True)
        self.assertEqual(self.c.mode, 'policy')
        self.assertEqual(self.c.gamepad_session, token)
        self.c.web_time = 0  # independent gamepad heartbeat keeps walking alive
        self.c.step()
        self.assertEqual(self.c.mode, 'policy')
        self.assertEqual(self.c.status()['input_source'], 'board_gamepad')
        self.assertNotIn(token, str(self.c.status()))

    def test_release_and_timeout_disarm(self):
        token = self.start()
        self.c.gamepad('release', session=token, seq=1, sent_at=time.monotonic())
        self.assertEqual(self.c.mode, 'off')
        self.assertIsNone(self.c.gamepad_session)
        self.assertEqual(COMMAND.unpack(self.bridge.messages[-1][1])[4], DISARM)
        self.start()
        self.c.gamepad_time = time.monotonic() - GAMEPAD_TIMEOUT - .01
        self.c.step()
        self.assertEqual(self.c.mode, 'off')
        self.assertEqual(self.c.twist, [0, 0, 0])
        self.assertIsNone(self.c.gamepad_session)

    def test_page_takeover_revokes_session_and_delayed_update(self):
        token = self.start()
        self.c.set_mode('policy')  # even selecting the same mode is explicit takeover
        with self.assertRaisesRegex(ValueError, 'session ended'):
            self.update(token, twist=[.2, 0, 0])
        self.assertEqual(self.c.twist, [0, 0, 0])
        token = self.start()
        self.c.set_mode('off')
        with self.assertRaises(ValueError):
            self.update(token)
        self.assertEqual(self.c.mode, 'off')

    def test_freshness_order_and_limits(self):
        token = self.start()
        for values in ([.41, 0, 0], [0, float('nan'), 0], [0, 0], [0, 0, 1.01]):
            with self.assertRaises(ValueError):
                self.update(token, twist=values)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.c.gamepad('update', session=token, seq=1, sent_at=time.monotonic()-1)
        self.update(token, seq=2, twist=[.1, 0, 0])
        with self.assertRaisesRegex(ValueError, 'out-of-order'):
            self.update(token, seq=1, twist=[.2, 0, 0])
        self.assertEqual(self.c.twist, [.1, 0, 0])
        with self.assertRaisesRegex(ValueError, 'another'):
            self.start()

    def test_start_requires_sensors_and_excludes_setup(self):
        with self.assertRaises(ValueError):
            self.c.gamepad('start', twist=[.1, 0, 0], sent_at=time.monotonic())
        self.c.rx_time = 0
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.start()
        self.c.rx_time = time.monotonic()
        self.c.set_mode('calibrate')
        with self.assertRaisesRegex(ValueError, 'exit'):
            self.start()
        self.assertIsNone(self.c.gamepad_session)

    def boot_step(self, now, fresh=True):
        if fresh:
            self.c.rx_time = now
        with mock.patch('controller.time.monotonic', return_value=now):
            self.c.step()

    def enable_startup_pose(self):
        self.c._zeros_confirmed = True
        self.boot_step(10.0)
        self.boot_step(10.0 + STARTUP_POSE_SETTLE_S + .01)
        self.assertEqual(self.c.mode, 'hold')
        self.assertTrue(self.c.startup_pose_active)

    def test_startup_waits_for_all_sensors_and_zero_echo(self):
        self.boot_step(10.0)
        self.boot_step(11.0)
        self.assertEqual(self.c.mode, 'shadow')  # no zero-position echo yet
        self.c._zeros_confirmed = True
        for feedback in (replace(self.c.feedback, mask=ALL_MASK ^ 1),
                         replace(self.c.feedback, flags=0),
                         replace(self.c.feedback, flags=9)):
            self.c.feedback = feedback
            self.boot_step(12.0)
            self.boot_step(13.0)
            self.assertEqual(self.c.mode, 'shadow')
        self.c.feedback = replace(self.c.feedback, mask=ALL_MASK, flags=1)
        self.boot_step(14.0)
        self.boot_step(14.1)
        self.boot_step(15.0, fresh=False)
        self.boot_step(15.01)
        self.boot_step(15.4)
        self.assertEqual(self.c.mode, 'shadow')  # stale feedback restarted settle time
        self.boot_step(15.6)
        self.assertEqual(self.c.mode, 'hold')

    def test_startup_pose_arms_measured_angles_then_holds_without_web(self):
        measured = tuple(v+1 for v in DEFAULT_DEG)
        self.c.feedback = replace(self.c.feedback, angles=measured)
        self.enable_startup_pose()
        packet = COMMAND.unpack(self.bridge.messages[-1][1])
        self.assertEqual(packet[4], ARM)
        self.assertEqual(list(packet[7:]), list(measured))
        self.c.feedback = replace(self.c.feedback, flags=3)
        self.c.web_time = 0
        self.boot_step(100.0)
        packet = COMMAND.unpack(self.bridge.messages[-1][1])
        self.assertEqual(packet[4], HOLD)
        self.assertEqual(list(packet[7:]), list(DEFAULT_DEG))
        self.assertEqual(self.c.status()['input_source'], 'startup_pose')
        self.assertTrue(self.c.command(twist=[.2, 0, 0], mouth=20)['ignored'])
        self.c.set_mode('off', page_exit=True)
        self.assertEqual(self.c.mode, 'hold')
        self.boot_step(101.0)
        self.assertEqual(self.c.mode, 'hold')

    def test_zero_echo_does_not_replace_saved_calibration_before_sync(self):
        self.c.zero_pos = [2100]*15
        stale = RAW.pack(b'DQR1', ALL_MASK, *([2047]*15), *([2047]*15))
        expected = RAW.pack(b'DQR1', ALL_MASK, *([2047]*15), *([2100]*15))
        self.c.receive_raw(stale)
        self.assertEqual(self.c.zero_pos, [2100]*15)
        self.assertFalse(self.c._zeros_confirmed)
        self.assertEqual(self.bridge.messages[-1][0], 'duck_cal')
        self.c.receive_raw(expected)
        self.assertTrue(self.c._zeros_confirmed)
        self.assertEqual(self.c.zero_pos, [2100]*15)

    def test_B_cancels_pending_and_active_startup_without_session(self):
        self.c.gamepad('stop', sent_at=time.monotonic())
        self.assertEqual(self.c.mode, 'off')
        self.assertFalse(self.c.startup_pose_pending)
        self.assertEqual(COMMAND.unpack(self.bridge.messages[-1][1])[4], DISARM)
        self.c._zeros_confirmed = True
        self.boot_step(10.0)
        self.boot_step(11.0)
        self.assertEqual(self.c.mode, 'off')
        self.c.startup_pose_pending = True
        self.c.mode = 'shadow'
        self.enable_startup_pose()
        self.c.gamepad('stop', sent_at=time.monotonic())
        self.boot_step(100.0)
        self.assertEqual(self.c.mode, 'off')
        self.assertFalse(self.c.startup_pose_active)

    def test_startup_sensor_failure_never_automatically_rearms(self):
        self.enable_startup_pose()
        self.c.feedback = replace(self.c.feedback, mask=ALL_MASK ^ 1, flags=3)
        self.boot_step(11.0)
        self.assertEqual(self.c.mode, 'shadow')
        self.assertEqual(COMMAND.unpack(self.bridge.messages[-1][1])[4], DISARM)
        self.c.feedback = replace(self.c.feedback, mask=ALL_MASK, flags=1)
        self.boot_step(12.0)
        self.boot_step(13.0)
        self.assertEqual(self.c.mode, 'shadow')
        self.assertFalse(self.c.startup_pose_pending)

    def test_A_transitions_from_boot_hold_to_walk(self):
        self.enable_startup_pose()
        self.c.feedback = replace(self.c.feedback, flags=3)
        self.c.rx_time = time.monotonic()
        token = self.start()
        self.assertEqual(self.c.mode, 'policy')
        self.assertFalse(self.c.startup_pose_active)
        self.assertFalse(self.c.arm_pending)  # torque is already on in hold
        self.update(token, twist=[.2, 0, 0])
        self.assertEqual(self.c.twist, [.2, 0, 0])

    def test_manual_shadow_cancels_startup_and_MCU_reset_cancels_hold(self):
        self.c.set_mode('shadow')
        self.assertFalse(self.c.startup_pose_pending)
        self.c.startup_pose_pending = True
        self.enable_startup_pose()
        self.c.feedback = replace(self.c.feedback, seq=100)
        packet = STATE.pack(b'DQS1', 1, 1, ALL_MASK,
                            1, 10000, 10000, 0, 0, 10000, 3000, 0, 0, 0,
                            0, 0, -16384, 0, 0, 0,
                            *DEFAULT_DEG, *([0.0]*15), *DEFAULT_DEG)
        self.c.receive(packet)
        self.assertEqual(self.c.mode, 'shadow')
        self.assertFalse(self.c.startup_pose_pending)
        self.assertFalse(self.c.startup_pose_active)
        self.assertFalse(self.c._zeros_confirmed)


class HostTest(unittest.TestCase):
    @staticmethod
    def state(axes=(0, 0, 0), a=False, b=False, lb=False, initialized=True):
        return dict(axes=list(axes), a=a, b=b, lb=lb, initialized=initialized)

    def test_gate_and_six_directions(self):
        gate = host.InputGate()
        self.assertFalse(gate.sample(self.state(a=True))['start'])
        self.assertFalse(gate.sample(self.state(a=True))['start'])
        gate.sample(self.state())
        self.assertTrue(gate.sample(self.state(a=True))['start'])
        for axes, expected in (
            ((0, -1, 0), [.2, 0, 0]), ((0, 1, 0), [-.2, 0, 0]),
            ((-1, 0, 0), [0, .15, 0]), ((1, 0, 0), [0, -.15, 0]),
            ((0, 0, -1), [0, 0, .5]), ((0, 0, 1), [0, 0, -.5])):
            self.assertEqual(gate.sample(self.state(axes, lb=True))['twist'], expected)
        self.assertEqual(gate.sample(self.state((0, -1, 0)))['twist'], [0, 0, 0])
        self.assertEqual(gate.sample(self.state((.1, .1, .12), lb=True))['twist'], [0, 0, 0])
        self.assertTrue(gate.sample(self.state(b=True))['stop'])
        self.assertEqual(gate.sample(self.state((0, -1, 0), lb=True))['twist'], [0, 0, 0])

    def test_joystick_abi_uses_linux_maps(self):
        stick = host.Joystick.__new__(host.Joystick)
        stick.fd = 123
        stick.axis_map = [host.ABS_Z, host.ABS_Y, host.ABS_X]
        stick.button_map = [host.BTN_LB, host.BTN_A, host.BTN_B]
        stick.yaw_axis = host.ABS_Z
        stick.axes, stick.buttons = {}, {}
        data = b''.join(host.EVENT.pack(0, v, k, n) for v, k, n in (
            (0, 0x82, 0), (-32768, 0x82, 1), (0, 0x82, 2),
            (1, 0x81, 0), (0, 0x81, 1), (0, 0x81, 2)))
        with mock.patch.object(host.os, 'read', side_effect=[data, BlockingIOError()]):
            state = stick.read()
        self.assertEqual(state['axes'], [0, -1, 0])
        self.assertTrue(state['initialized'])
        self.assertTrue(state['lb'])
        self.assertEqual(state['button_events'], [])  # initialization is not a physical press
        tap = host.EVENT.pack(1, 1, 1, 2) + host.EVENT.pack(2, 0, 1, 2)
        with mock.patch.object(host.os, 'read', side_effect=[tap, BlockingIOError()]):
            state = stick.read()
        self.assertFalse(state['b'])
        self.assertEqual(state['button_events'], [
            {'code': host.BTN_B, 'pressed': True}, {'code': host.BTN_B, 'pressed': False}])
        self.assertTrue(host.InputGate().sample(state)['stop'])
        with mock.patch.object(host.os, 'read', return_value=b''):
            with self.assertRaises(OSError): stick.read()

    def test_short_taps_and_preview_summary(self):
        gate, summary = host.InputGate(), host.PreviewSummary()
        state = self.state()
        gate.sample(state)
        state['button_events'] = [{'code': host.BTN_A, 'pressed': True},
                                  {'code': host.BTN_A, 'pressed': False}]
        mapped = gate.sample(state)
        self.assertTrue(mapped['start'])
        summary.observe(state, mapped)
        state = self.state((0, -1, .5), lb=True)
        mapped = gate.sample(state)
        summary.observe(state, mapped)
        state = self.state()
        state['button_events'] = [{'code': host.BTN_B, 'pressed': True},
                                  {'code': host.BTN_B, 'pressed': False}]
        mapped = gate.sample(state)
        self.assertTrue(mapped['stop'])
        summary.observe(state, mapped)
        result = summary.report()
        self.assertEqual(result['observed_buttons'], ['A', 'B', 'LB'])
        self.assertEqual(result['axis_ranges']['left_y'], [-1, 0])
        self.assertTrue(result['motion_observed'])
        self.assertTrue(result['start_observed'])
        self.assertTrue(result['stop_observed'])

    def test_host_url_restricted_to_board(self):
        for url in ('http://example.com:9527', 'https://localhost', 'http://localhost/api'):
            with self.assertRaises(ValueError): host.Client(url)
        host.Client('http://127.0.0.1:9527')

    def test_B_sends_stop_even_before_walk_session_exists(self):
        client = host.Client('http://127.0.0.1:9527')
        self.assertIsNone(client.session)
        with mock.patch.object(client, 'request', return_value={'ok': True}) as request:
            client.stop()
        self.assertEqual(request.call_args.args[0], 'gamepad')
        self.assertEqual(request.call_args.args[1]['action'], 'stop')
        self.assertIsNone(request.call_args.args[1]['session'])

    def test_reconnect_only_paired_trusted_device(self):
        for paired, trusted, connected, expected in (
            (False, False, False, 1), (True, False, False, 1),
            (True, True, True, 1), (True, True, False, 2)):
            text = f'Paired: {"yes" if paired else "no"}\nTrusted: {"yes" if trusted else "no"}\nConnected: {"yes" if connected else "no"}'
            result = subprocess.CompletedProcess([], 0, stdout=text, stderr='')
            stopped = mock.Mock()
            stopped.wait.side_effect = [False, True]
            missing = threading.Event(); missing.set()
            with mock.patch.object(host.subprocess, 'run', return_value=result) as run, mock.patch('builtins.print'):
                host.reconnect('47:84:65:FD:BE:E7', stopped, missing)
            self.assertEqual(run.call_count, expected)
            if expected == 2:
                self.assertEqual(run.call_args.args[0][-2:], ['connect', '47:84:65:FD:BE:E7'])


if __name__ == '__main__':
    unittest.main()
