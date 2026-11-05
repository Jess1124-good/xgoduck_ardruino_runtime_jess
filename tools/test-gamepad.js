// Offline input checks. No Arduino libraries, HTTP requests or motor commands.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../assets/gamepad.js'), 'utf8');
const DuckGamepad = vm.runInNewContext(source + '\nDuckGamepad');
const pad = (axes = [0, 0, 0, 0], buttons = [], extra = {}) => ({
  index: 0, id: 'Test Xbox controller', connected: true, mapping: 'standard', axes,
  buttons: Array.from({length: 17}, (_, i) => ({pressed: buttons.includes(i), value: buttons.includes(i) ? 1 : 0})),
  ...extra,
});
const zero = sample => assert.ok(sample.twist.every(v => v === 0));
const input = new DuckGamepad();
zero(input.sample([pad([0, -1, 0, 0], [4])]));
input.setEnabled(true);
// Connecting with LB already held cannot cause movement.
zero(input.sample([pad([0, -1, 0, 0], [4])]));
assert.equal(input.ready, false);
zero(input.sample([pad()]));
assert.equal(input.ready, true);
const directions = [
  [[0, -1, 0, 0], [0.2, 0, 0]],  // forward
  [[0, 1, 0, 0], [-0.2, 0, 0]],   // backward
  [[-1, 0, 0, 0], [0, 0.15, 0]],  // left
  [[1, 0, 0, 0], [0, -0.15, 0]],  // right
  [[0, 0, -1, 0], [0, 0, 0.5]],   // rotate left
  [[0, 0, 1, 0], [0, 0, -0.5]],   // rotate right
];
for (const [axes, expected] of directions) {
  const result = input.sample([pad(axes, [4])]);
  result.twist.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-12));
}
zero(input.sample([pad([0.1, -0.1, 0.12, 0], [4])]));
zero(input.sample([pad([0, -1, 0, 0])])); // LB release zeros immediately
const maximum = input.sample([pad([-1, -1, -1, 0], [4])], {scale: 1});
maximum.twist.forEach((v, i) => assert.equal(v, [0.4, 0.3, 1][i]));
// Zero / speed / mode change must require a new neutral-and-release cycle.
input.resetGate();
zero(input.sample([pad([0, -1, 0, 0], [4])]));
input.sample([pad()]);
assert.equal(input.sample([pad([0, -1, 0, 0], [4, 1])]).stop, true);
assert.equal(input.sample([pad([0, -1, 0, 0], [4, 1])]).stop, false); // held B
zero(input.sample([pad([0, -1, 0, 0], [4])]));
input.sample([pad()]);
assert.equal(input.sample([]).stop, true);
assert.equal(input.sample([]).stop, false);
zero(input.sample([pad([0, -1, 0, 0], [4])])); // reconnect with LB held
input.sample([pad()]);
// A different controller cannot silently inherit control after a disconnect.
const other = pad([0, -1, 0, 0], [4], {index: 1, id: 'Other controller'});
assert.equal(input.sample([other]).stop, true);
zero(input.sample([other]));
input.sample([pad()]);
zero(input.sample([pad([0, -1, 0, 0], [4])], {focused: false}));
zero(input.sample([pad([0, -1, 0, 0], [4])], {focused: true}));
input.sample([pad()]);
assert.equal(input.sample([pad([NaN, 0, 0, 0], [4])]).stop, true);
zero(input.sample([pad([0, -1, 0, 0], [4])]));
input.setEnabled(true);
zero(input.sample([pad([0, -1, 0, 0], [4], {mapping: ''})]));
zero(input.sample([pad([0, -1, 0, 0], [4], {buttons: []})]));
input.setEnabled(false);
zero(input.sample([pad([0, -1, 0, 0], [4])]));
console.log('PASS: directions, bounds, dead zone, LB release, B, neutral gate, disconnect, controller identity, focus and invalid input');

// Run the actual page scripts with a small DOM/transport fixture. All HTTP is
// intercepted here; these checks never connect to a running Arduino App.
function page(secure = true) {
  const elements = new Map(), events = {}, timers = {}, posts = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'gamepad-speed' ? '0.5' : '0', checked: false,
      textContent: '', disabled: false, style: {}, firstElementChild: {style: {}},
      hasPointerCapture: () => false,
      insertAdjacentHTML: (_where, html) => {
        for (const match of html.matchAll(/id="([^"]+)"/g)) element(match[1]);
      },
    });
    return elements.get(id);
  }
  const html = fs.readFileSync(path.join(__dirname, '../assets/index.html'), 'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) element(match[1]);
  const modes = Object.fromEntries(Array.from(html.matchAll(/data-mode="([^"]+)"/g),
    match => [match[1], {dataset: {mode: match[1]}, disabled: false}]));
  const state = {mode: 'shadow', feedback_hz: 100, inference_hz: 50,
    servo_ids: [], imu_ok: true, bridge_baud: 2000000, control_ready: true};
  const fixture = {pads: [], focused: true, failAccess: false};
  const document = {
    hidden: false, hasFocus: () => fixture.focused,
    getElementById: id => {
      assert.ok(elements.has(id), `Missing page element ${id}`);
      return elements.get(id);
    },
    querySelectorAll: selector => Object.values(modes).filter(button =>
      selector === '[data-mode]' || selector.includes(`[data-mode="${button.dataset.mode}"]`)),
    addEventListener: (name, callback) => {events[name] = callback;},
  };
  const context = vm.createContext({
    document, isSecureContext: secure, Blob, console,
    navigator: {getGamepads: () => {
      if (fixture.failAccess) throw new Error('Blocked by browser');
      return fixture.pads;
    }, sendBeacon: () => true},
    addEventListener: (name, callback) => {events[name] = callback;},
    setInterval: (callback, ms) => {timers[ms] = callback;},
    fetch: async (url, options = {}) => {
      if (options.method === 'POST') {
        const body = JSON.parse(options.body);
        posts.push({url, body});
        if (url === '/api/mode' && !(body.page_exit && ['board_gamepad','startup_pose'].includes(state.input_source))) state.mode = body.mode;
      }
      return {ok: true, json: async () => url === '/api/status' ? {...state} : {ok: true}};
    },
  });
  context.window = context;
  vm.runInContext(source, context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8'), context);
  const flush = async () => {for (let i = 0; i < 12; i++) await Promise.resolve();};
  return {elements, events, timers, posts, modes, fixture, context, document, state, flush,
    tick: async () => {await vm.runInContext('sendCommand()', context); await flush();},
    lastTwist: () => posts.filter(p => p.url === '/api/command').at(-1).body.twist,
    offCount: () => posts.filter(p => p.url === '/api/mode' && p.body.mode === 'off').length,
    enable: async () => {
      element('gamepad-enable').checked = true;
      element('gamepad-enable').onchange();
      await flush();
    },
  };
}

(async () => {
  const p = page();
  await p.timers[250](); // initial server mode
  p.events.keydown({code: 'KeyW', key: 'w'});
  await p.flush();
  assert.deepEqual(p.lastTwist(), [0.2, 0, 0]); // original keyboard still works
  p.fixture.pads = [pad([0, -1, 0, 0], [4])];
  await p.enable();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, -1, 0], [4])]; await p.tick();
  assert.deepEqual(p.lastTwist(), [0.2, 0, 0.5]);
  assert.equal(p.offCount(), 0);
  assert.ok(p.posts.every(post => post.url !== '/api/mode')); // never auto-enable motors
  await p.modes.policy.onclick(); await p.tick(); await p.timers[250]();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]); // mode change blocks a held stick
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  assert.deepEqual(p.lastTwist(), [0.2, 0, 0]);
  p.elements.get('zero').onclick(); await p.flush(); await p.tick();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]); // held stick cannot undo Zero
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  p.elements.get('gamepad-speed').value = '1';
  p.elements.get('gamepad-speed').onchange(); await p.flush();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  assert.deepEqual(p.lastTwist(), [0.4, 0, 0]);
  p.fixture.pads = [pad([0, -1, 0, 0], [4, 1])]; await p.tick();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  assert.equal(p.offCount(), 1);
  await p.tick(); assert.equal(p.offCount(), 1);
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  p.fixture.pads = []; p.events.gamepaddisconnected(); await p.flush();
  assert.equal(p.offCount(), 2);
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.fixture.pads = [pad()]; await p.tick();
  p.fixture.pads = [pad([0, -1, 0, 0], [4])]; await p.tick();
  p.fixture.focused = false; p.events.blur(); await p.flush();
  assert.equal(p.offCount(), 3);
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.fixture.focused = true; await p.tick();
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.document.hidden = true; p.events.visibilitychange(); await p.flush();
  assert.equal(p.offCount(), 4);
  assert.deepEqual(p.lastTwist(), [0, 0, 0]);
  p.document.hidden = false;
  p.fixture.failAccess = true; await p.tick();
  assert.equal(p.elements.get('gamepad-enable').checked, false);
  assert.equal(p.offCount(), 5);
  assert.match(p.elements.get('gamepad-status').textContent, /access failed/);
  const insecure = page(false);
  assert.equal(insecure.elements.get('gamepad-enable').disabled, true);
  assert.match(insecure.elements.get('gamepad-context').textContent, /localhost/);
  const board = page();
  board.state.input_source = 'board_gamepad'; board.state.command = [.1, 0, .2];
  board.state.mode = 'policy'; board.state.board_gamepad = {device: 'Xbox Wireless Controller'};
  await board.timers[250]();
  assert.equal(board.elements.get('gamepad-enable').disabled, true);
  assert.match(board.elements.get('board-gamepad-status').textContent, /Xbox Wireless Controller/);
  assert.equal(board.elements.get('vxValue').textContent, '0.10');
  board.document.hidden = true; board.events.visibilitychange(); await board.flush();
  assert.equal(board.state.mode, 'policy');
  assert.equal(board.posts.find(p => p.url === '/api/mode').body.page_exit, true);
  board.elements.get('stop').onclick(); await board.flush();
  assert.equal(board.state.mode, 'off');
  const startup = page();
  startup.state.input_source = 'startup_pose'; startup.state.mode = 'hold';
  startup.state.startup_pose = {active: true};
  await startup.timers[250]();
  assert.match(startup.elements.get('board-gamepad-status').textContent, /default pose is holding/);
  startup.document.hidden = true; startup.events.visibilitychange(); await startup.flush();
  assert.equal(startup.state.mode, 'hold');
  startup.elements.get('stop').onclick(); await startup.flush();
  assert.equal(startup.state.mode, 'off');
  console.log('PASS: page scripts → mocked API, keyboard, no automatic enable, mode/Zero/speed gates, B, disconnect, blur/background, API denial and HTTP context hint');
})().catch(error => {console.error(error); process.exitCode = 1;});
