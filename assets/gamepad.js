// Standard Gamepad layout: Xbox / compatible GameSir controllers.
// Kept independent of the UI and transport so input can be checked without motors.
class DuckGamepad {
  constructor() {
    this.enabled = false;
    this.index = null;
    this.id = null;
    this.present = false;
    this.ready = false;
    this.bDown = false;
  }

  setEnabled(enabled) {
    this.enabled = !!enabled;
    this.index = this.id = null;
    this.present = this.ready = this.bDown = false;
  }

  resetGate() {
    this.ready = false;
  }

  sample(pads, {focused = true, scale = 0.5} = {}) {
    const result = {twist: [0, 0, 0], stop: false, message: 'Gamepad disabled'};
    if (!this.enabled) return result;
    const connected = Array.from(pads || []).filter(p => p && p.connected);
    // Keep the selected controller; another connected pad must not take over.
    let pad = this.index === null
      ? connected.find(p => p.mapping === 'standard')
      : connected.find(p => p.index === this.index && p.id === this.id);
    if (!pad) {
      result.stop = this.present;
      this.present = this.ready = this.bDown = false;
      result.message = connected.length
        ? 'No selected standard controller. Use PC / XInput mode, then disable and enable gamepad.'
        : 'Connect a controller to this computer and press a button.';
      return result;
    }
    if (this.index === null) {
      this.index = pad.index;
      this.id = pad.id;
    }
    result.device = pad.id;
    if (pad.mapping !== 'standard' || pad.axes.length < 4 || pad.buttons.length < 6 ||
        !Array.from(pad.axes).every(Number.isFinite)) {
      result.stop = this.present;
      this.present = this.ready = false;
      result.message = 'Unsupported controller layout. Switch to PC / XInput mode.';
      return result;
    }
    this.present = true;
    const pressed = i => !!pad.buttons[i]?.pressed || pad.buttons[i]?.value > 0.5;
    const b = pressed(1), lb = pressed(4);
    result.stop = b && !this.bDown;
    this.bDown = b;
    if (!focused || b) {
      this.ready = false;
      result.message = b ? 'B: torque off. Release LB and center both sticks.'
        : 'Paused: return to this page, release LB and center both sticks.';
      return result;
    }
    const deadzone = 0.12;
    if (!this.ready) {
      this.ready = !lb && Array.from(pad.axes).slice(0, 4).every(v => Math.abs(v) <= deadzone);
      result.message = this.ready ? 'Ready. Hold LB to move; B turns torque off.'
        : 'Release LB and center both sticks to get ready.';
      return result;
    }
    if (!lb) {
      result.message = 'Ready. Hold LB to move; B turns torque off.';
      return result;
    }
    const axis = i => {
      const value = Math.max(-1, Math.min(1, pad.axes[i]));
      return Math.abs(value) <= deadzone ? 0
        : Math.sign(value) * (Math.abs(value) - deadzone) / (1 - deadzone);
    };
    const speed = Number.isFinite(scale) ? Math.max(0, Math.min(1, scale)) : 0;
    result.twist = [-axis(1) * 0.4 * speed, -axis(0) * 0.3 * speed, -axis(2) * speed];
    result.message = `LB held · speed ${Math.round(speed * 100)}% · B: torque off`;
    return result;
  }
}
