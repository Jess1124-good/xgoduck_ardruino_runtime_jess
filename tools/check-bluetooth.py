"""Read-only Bluetooth/HID report. Run on the UNO Q host, outside App containers.

Does not power on, scan, pair, trust, connect, install or start anything.
"""
import gzip
import json
import platform
import subprocess
from pathlib import Path


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return dict(returncode=result.returncode,
                    stdout=result.stdout.strip(), stderr=result.stderr.strip()[:1000])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(error=str(exc))


def kernel_config():
    try:
        return gzip.decompress(Path('/proc/config.gz').read_bytes()).decode()
    except OSError:
        return read('/boot/config-' + platform.release()) or ''


def main():
    config = kernel_config().splitlines()
    names = ('CONFIG_BT', 'CONFIG_BT_BREDR', 'CONFIG_BT_LE', 'CONFIG_BT_HIDP',
             'CONFIG_BT_HCIUART_QCA', 'CONFIG_UHID', 'CONFIG_INPUT_EVDEV',
             'CONFIG_INPUT_JOYDEV', 'CONFIG_HID_GENERIC', 'CONFIG_HID_MICROSOFT',
             'CONFIG_HID_SONY', 'CONFIG_HID_PLAYSTATION', 'CONFIG_HID_NINTENDO',
             'CONFIG_INPUT_JOYSTICK', 'CONFIG_JOYSTICK_XPAD')
    settings = {}
    for name in names:
        value = next((line.split('=', 1)[1] for line in config
                      if line.startswith(name + '=')), None)
        settings[name] = value if value is not None else (
            'disabled' if '# ' + name + ' is not set' in config else 'not listed')
    adapters = []
    for adapter in sorted(Path('/sys/class/bluetooth').glob('hci*')):
        driver = adapter / 'device/driver'
        adapters.append(dict(name=adapter.name, sysfs=str(adapter.resolve()),
                             driver=driver.resolve().name if driver.exists() else None))
    inputs = []
    for event in sorted(Path('/sys/class/input').glob('event*')):
        device = event / 'device'
        inputs.append(dict(event=event.name, name=read(device / 'name'),
                           bus=read(device / 'id/bustype'), vendor=read(device / 'id/vendor'),
                           product=read(device / 'id/product'), uniq=read(device / 'uniq'),
                           capabilities={key: read(device / 'capabilities' / key)
                                         for key in ('ev', 'key', 'abs')},
                           node_visible=(Path('/dev/input') / event.name).exists()))
    radio = []
    for item in sorted(Path('/sys/class/rfkill').glob('rfkill*')):
        if read(item / 'type') == 'bluetooth':
            radio.append({key: read(item / key) for key in ('name', 'soft', 'hard')})
    board = read('/sys/firmware/devicetree/base/compatible')
    report = dict(board=board.split('\0') if board else None, kernel=platform.release(),
                  kernel_config=settings, adapters=adapters, rfkill=radio,
                  hid_drivers=sorted(p.name for p in Path('/sys/bus/hid/drivers').glob('*')
                                     if p.is_dir()),
                  bluez_version=command('bluetoothctl', '--version'),
                  adapter_state=command('bluetoothctl', 'show'),
                  devices=command('bluetoothctl', 'devices'), input_devices=inputs,
                  note='Visible devices reflect this process namespace. D-Bus failure or missing '
                       '/dev/input inside a sandbox/container does not prove the host lacks support.')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
