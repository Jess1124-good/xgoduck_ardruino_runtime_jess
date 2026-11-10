const $=id=>document.getElementById(id);
let statusBusy=false, commandBusy=false, commandPending=false;
for(let i=0;i<4;i++) $('head-controls').insertAdjacentHTML('beforeend',`<label>head ${i+1}<input id="head${i}" type="range" min="-1" max="1" value="0" step="0.02"></label>`);
$('head-controls').insertAdjacentHTML('beforeend','<label>Mouth 34 (°)<input id="mouth" type="range" min="0" max="30" value="0" step="1"></label>');
// A stalled request must never wedge the 50 ms heartbeat loop: sendCommand()
// holds commandBusy until this promise settles, and the runtime disarms after
// 1 s without a heartbeat. Without a timeout one slow fetch drops the duck.
async function post(path, body, timeoutMs = 800){
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try{
    const r = await fetch('/api/' + path, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body), signal: ac.signal});
    const x = await r.json();
    if(!r.ok) throw new Error(x.detail || 'request failed');
    return x;
  } finally {
    clearTimeout(timer);
  }
}
function showError(e){$('message').textContent=e.message;}
async function setMode(mode){if(gamepad.enabled)resetMotion();try{await post('mode',{mode});$('message').textContent='Mode updated';}catch(e){showError(e);}}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('pick').onclick=async()=>{try{const r=await post('pick',{});$('message').textContent=`Pick started · ${r.model}`;}catch(e){showError(e);}};
$('roulade').onclick=async()=>{try{const r=await post('roulade',{});$('message').textContent=`Roulade · ${r.model}`;}catch(e){showError(e);}};
$('walk-slot').onchange=async()=>{const want=$('walk-slot').value;try{const r=await post('walk_model',{slot:want});$('message').textContent=`Walk slot ${r.slot} · ${r.model}`;}catch(e){showError(e);$('walk-slot').value='main';}};
$('imu-cal').onclick=async()=>{$('message').textContent='Calibrating IMU — hold the duck still in Default pose';try{const r=await post('imu/calibrate',{});$('message').textContent=`IMU calibrated · roll ${r.imu_bias_deg[0].toFixed(1)}° pitch ${r.imu_bias_deg[1].toFixed(1)}° · gyro [${r.gyro_bias_dps.join(', ')}] °/s · ${r.samples} samples`;}catch(e){showError(e);}};
fetch('/api/status').then(r=>r.json()).then(s=>{if(s.walk_model)$('walk-slot').value=s.walk_model.slot;}).catch(()=>{});
$('stop').onclick=()=>{zero();setMode('off')};
const keys=new Set(), sticks={left:{x:0,y:0},right:{x:0,y:0}}, resetSticks=[];
let motion=[0,0,0], gamepadMotion=[0,0,0], lastMode=null, boardControl=false, boardMotion=[0,0,0];
const gamepad=new DuckGamepad();
function pollGamepad(){
  if(!gamepad.enabled||boardControl)return;
  try{
    const sample=gamepad.sample(navigator.getGamepads(),{focused:!document.hidden&&document.hasFocus(),scale:+$('gamepad-speed').value});
    gamepadMotion=sample.twist;
    $('gamepad-status').textContent=sample.message;
    $('gamepad-device').textContent=sample.device||'';
    if(sample.stop){resetMotion();setMode('off');}
  }catch(e){
    gamepad.setEnabled(false);$('gamepad-enable').checked=false;
    resetMotion();setMode('off');
    $('gamepad-status').textContent='Gamepad access failed: '+e.message;
  }
}
const gamepadSupported=window.isSecureContext&&typeof navigator.getGamepads==='function';
$('gamepad-enable').disabled=!gamepadSupported;
if(!gamepadSupported)$('gamepad-context').textContent=window.isSecureContext
  ? 'This browser does not provide gamepad access. Open this page in a supported desktop browser.'
  : 'Gamepad access needs HTTPS or localhost. On your computer run: ssh -N -L 9527:127.0.0.1:9527 arduino@<board-IP>, then open http://localhost:9527.';
$('gamepad-enable').onchange=()=>{
  gamepad.setEnabled($('gamepad-enable').checked);zero();
  if(!gamepad.enabled){$('gamepad-status').textContent='Gamepad disabled';$('gamepad-device').textContent='';}
};
$('gamepad-speed').onchange=()=>{if(gamepad.enabled)zero();};
window.addEventListener('gamepaddisconnected',()=>{pollGamepad();updateMotion();sendCommand();});
const deadzone=v=>Math.abs(v)<.1?0:v;
function updateMotion(){
  const key=(a,b)=>keys.has(a)-keys.has(b);
  motion=boardControl?[...boardMotion]:gamepad.enabled?[...gamepadMotion]:[keys.has('w')||keys.has('s')?key('w','s')*.2:deadzone(sticks.left.y)*.4,
    keys.has('a')||keys.has('d')?key('a','d')*.15:deadzone(-sticks.left.x)*.3,
    keys.has('q')||keys.has('e')?key('q','e')*.5:deadzone(-sticks.right.x)];
  ['vx','vy','wz'].forEach((id,i)=>$(id+'Value').textContent=motion[i].toFixed(2));
}
async function sendCommand(){
  pollGamepad();updateMotion();
  if(commandBusy){commandPending=true;return;}
  commandBusy=true;commandPending=false;
  try{await post('command',{twist:[...motion],head:[0,1,2,3].map(i=>+$('head'+i).value),mouth:+$('mouth').value});}
  catch(e){if(gamepad.enabled)resetMotion();showError(e);}
  finally{commandBusy=false;if(commandPending)sendCommand();}
}
function joystick(id,side){
  const zone=$(id),knob=zone.firstElementChild;
  let pointer=null;
  function reset(){
    const old=pointer;pointer=null;
    sticks[side]={x:0,y:0};knob.style.transform='translate(0px,0px)';
    if(old!==null&&zone.hasPointerCapture(old))zone.releasePointerCapture(old);
  }
  resetSticks.push(reset);
  function move(e){
    const b=zone.getBoundingClientRect(),radius=(zone.clientWidth-knob.offsetWidth)/2;
    let dx=e.clientX-b.left-b.width/2,dy=e.clientY-b.top-b.height/2;
    const distance=Math.hypot(dx,dy);
    if(distance>radius){dx*=radius/distance;dy*=radius/distance;}
    knob.style.transform=`translate(${dx}px,${dy}px)`;
    sticks[side]={x:dx/radius,y:-dy/radius};updateMotion();
  }
  zone.onpointerdown=e=>{if(pointer!==null||e.button!==0)return;e.preventDefault();pointer=e.pointerId;zone.setPointerCapture(pointer);move(e);sendCommand();};
  zone.onpointermove=e=>{if(e.pointerId===pointer)move(e);};
  const release=e=>{if(e.pointerId!==pointer)return;reset();updateMotion();sendCommand();};
  zone.onpointerup=zone.onpointercancel=zone.onlostpointercapture=release;
}
joystick('joy-left','left');joystick('joy-right','right');
function resetMotion(){keys.clear();resetSticks.forEach(reset=>reset());gamepad.resetGate();gamepadMotion=[0,0,0];updateMotion();}
function zero(){resetMotion();sendCommand();}
$('zero').onclick=()=>{if(boardControl)setMode('off');else zero();};
['leg-alpha','head-alpha'].forEach(id=>$(id).onchange=()=>post('filter',{leg:+$('leg-alpha').value,head:+$('head-alpha').value}).catch(showError));
function keyCommand(){updateMotion();sendCommand();}
window.addEventListener('keydown',e=>{if(e.code==='Space'){e.preventDefault();$('stop').click();return;}const k=e.key.toLowerCase();if('wasdqe'.includes(k)&&k.length===1){keys.add(k);keyCommand();}});
window.addEventListener('keyup',e=>{const k=e.key.toLowerCase();if(keys.delete(k))keyCommand();});
window.addEventListener('blur',()=>{zero();if(gamepad.enabled&&!boardControl)setMode('off');});
document.addEventListener('visibilitychange',()=>{if(document.hidden){keys.clear();zero();post('mode',{mode:'off',page_exit:true}).catch(()=>{});}});
window.addEventListener('pagehide',()=>navigator.sendBeacon('/api/mode',new Blob([JSON.stringify({mode:'off',page_exit:true})],{type:'application/json'})));
setInterval(()=>{if(!document.hidden&&!commandBusy)sendCommand();},50);
setInterval(async()=>{if(statusBusy||document.hidden)return;statusBusy=true;try{const ac=new AbortController();const tm=setTimeout(()=>ac.abort(),2500);const r=await fetch('/api/status',{signal:ac.signal}).finally(()=>clearTimeout(tm));if(!r.ok)throw new Error('status read failed');const s=await r.json();const modeLabel={shadow:'inference only',off:'torque off',hold:'default pose',policy:'walk',calibrate:'calibrate',servo_debug:'servo setup'};$('rx').textContent=s.feedback_hz.toFixed(1)+' Hz';$('rl').textContent=s.inference_hz.toFixed(1)+' Hz';$('servos').textContent=(s.servo_ids?.length||0)+'/15';$('imu').textContent=s.imu_ok?'online':'offline';$('mode').textContent=(modeLabel[s.mode]||s.mode)+(s.enabled?' · enabled':' · torque off');$('message').textContent=s.last_error||`Bridge ${(s.bridge_baud/1e6).toFixed(0)} Mbps · state age ${(s.feedback_age_ms||0).toFixed(1)} ms`;
document.querySelectorAll('[data-mode="hold"],[data-mode="policy"]').forEach(b=>b.disabled=!s.control_ready);
const recovery=s.recovery, pick=s.pick, roulade=s.roulade;
const boardActive=s.input_source==='board_gamepad';
if(boardActive!==boardControl){boardControl=boardActive;resetMotion();}
boardMotion=boardControl&&Array.isArray(s.command)?s.command:[0,0,0];
$('board-gamepad-status').textContent=boardControl?`Board Bluetooth: ${s.board_gamepad?.device||'controller'} · active · LB: move · B: torque off`:s.startup_pose?.active?'Startup default pose is holding · A: walk · B: torque off':s.startup_pose?.pending?'Startup: waiting for all servos, IMU and calibration to be ready':'Board Bluetooth: center sticks, release LB and press A to start.';
$('gamepad-enable').disabled=!gamepadSupported||boardControl;
updateMotion();
if(s.mode!==lastMode){if(gamepad.enabled)resetMotion();lastMode=s.mode;}
const upright=(s.mode==='shadow'||s.mode==='policy')&&recovery&&recovery.active&&recovery.phase==='walk';
$('pick').disabled=!upright||(pick&&pick.active)||(roulade&&roulade.active);
$('roulade').disabled=$('pick').disabled;
if(recovery){const phaseLabel=roulade&&roulade.active?'roulade':pick&&pick.active?'pick':({walk:'walk',default_pose:'get-up · action = 0',getup:'get-up'}[recovery.phase]||recovery.phase);
$('recovery-phase').textContent=recovery.active?phaseLabel:'idle';$('active-model').textContent=s.active_model||'—';$('tilt-angle').textContent=recovery.angle_deg==null?'—':recovery.angle_deg.toFixed(1)+'°';
$('recovery-timer').textContent=!recovery.active?'—':roulade&&roulade.active?`roulade ${roulade.remaining_s.toFixed(2)} / ${roulade.seconds.toFixed(2)} s`:pick&&pick.active?`pick φ ${pick.phi.toFixed(2)} / 1.00`:recovery.phase==='default_pose'?`hold ${recovery.hold_remaining_s.toFixed(2)} s left`:recovery.phase==='getup'?`upright ${recovery.stand_elapsed_s.toFixed(2)} / 1.00 s`:`fallen ${recovery.fall_elapsed_s.toFixed(2)} / 0.15 s`;
if(pick&&pick.active)$('mouth').value=Math.round(s.mouth||0);}
for(const [id,values]of [['acc-values',s.acc],['gyro-values',s.gyro],['gravity-values',s.gravity]])$(id).textContent=values?values.map(x=>x.toFixed(3)).join(' / '):'—';
$('command-health').textContent=`sent ${s.sent} · MCU echo ${s.mcu_command_seq??'—'} · command age ${s.mcu_command_age_us<1e9?(s.mcu_command_age_us/1000).toFixed(1)+' ms':'—'} · gaps ${s.sequence_gaps} · rejected ${s.mcu_invalid_commands??0}`;
if(s.angles)$('joints').innerHTML=s.motors.map((id,i)=>`<tr class="${s.servo_ids.includes(id)?'':'missing'}"><td>${id}</td><td>${s.angles[i].toFixed(1)}</td><td>${s.targets[i].toFixed(1)}</td></tr>`).join('');
}catch(e){showError(e);}finally{statusBusy=false;}},250);
