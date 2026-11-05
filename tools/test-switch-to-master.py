"""Check real switch sequencing against a fake CLI; no Apps are touched."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('switch_to_master', ROOT / 'tools/switch-to-master.py')
switch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switch)
OLD = 'user:xgoduck_runtime_arduino'
MASTER = 'user:xgoduck_runtime_arduino-master'


def table(states):
    return 'ID STATUS NAME\n' + ''.join(f'{key} {value} XGO Duck\n' for key, value in states.items())


class SwitchTest(unittest.TestCase):
    def execute(self, snapshots):
        actions = []
        def invoke(args, **kwargs):
            actions.append(args[2:])
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.object(switch.subprocess, 'check_output', side_effect=[table(s) for s in snapshots]), \
             mock.patch.object(switch.subprocess, 'run', side_effect=invoke), \
             mock.patch.object(switch.time, 'sleep'), mock.patch('builtins.print'):
            switch.switch_to_master(ROOT)
        return actions

    def test_master_already_running_with_duplicate_display_names(self):
        actions = self.execute([
            {OLD: 'stopped', MASTER: 'running'},
            {OLD: 'stopped', MASTER: 'stopping'},
            {OLD: 'stopped', MASTER: 'stopped'}])
        self.assertEqual(actions, [['stop', str(ROOT)], ['start', str(ROOT)]])

    def test_old_app_running(self):
        actions = self.execute([
            {OLD: 'running', MASTER: 'stopped'}, {OLD: 'stopped', MASTER: 'stopped'}])
        self.assertEqual(actions, [['stop', str(ROOT.parent / 'xgoduck_runtime_arduino')],
                                   ['start', str(ROOT)]])

    def test_cold_start_and_stopping_state(self):
        self.assertEqual(self.execute([{}, {}]), [['start', str(ROOT)]])
        self.assertEqual(self.execute([{MASTER: 'stopping'}, {MASTER: 'stopped'}]),
                         [['start', str(ROOT)]])

    def test_stop_failure_prevents_start(self):
        with mock.patch.object(switch.subprocess, 'check_output', return_value=table({MASTER: 'running'})), \
             mock.patch.object(switch.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'stop')) as run, \
             mock.patch('builtins.print'):
            with self.assertRaises(subprocess.CalledProcessError):
                switch.switch_to_master(ROOT)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][2], 'stop')

    def test_stop_timeout_prevents_start(self):
        with mock.patch.object(switch.subprocess, 'check_output', return_value=table({MASTER: 'stopping'})), \
             mock.patch.object(switch.subprocess, 'run') as run:
            with self.assertRaises(TimeoutError):
                switch.switch_to_master(ROOT, timeout=0)
        run.assert_not_called()

    def test_unrelated_app_or_query_failure_prevents_mutation(self):
        for output in (table({'user:other': 'running'}), '[ERROR] cannot read status'):
            with mock.patch.object(switch.subprocess, 'check_output', return_value=output), \
                 mock.patch.object(switch.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    switch.switch_to_master(ROOT)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
