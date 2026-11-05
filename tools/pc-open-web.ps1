# 打开 XGO Duck 上位机网页（走 USB，adb forward，不依赖 WiFi）
#
# 背景：板子的 wlan0 会在「手机热点 192.168.43.x」和「校园网 gpnu.edu.cn 10.214.x.x」
# 之间自动切换，IP 一变书签就失效。USB 转发不受影响。
#
# 用法：  powershell -ExecutionPolicy Bypass -File tools\pc-open-web.ps1
#         powershell -ExecutionPolicy Bypass -File tools\pc-open-web.ps1 -NoBrowser
param(
    [int]$LocalPort = 19527,   # PC 侧端口（9527 常被 VS Code 占用）
    [int]$RemotePort = 9527,   # 板子上的 WebUI 端口
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$adb = "C:\Users\34511\AppData\Local\Arduino15\packages\arduino\tools\adb\32.0.0\adb.exe"

if (-not (Test-Path $adb)) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd -eq $null) { throw "adb.exe not found; is Arduino App Lab installed?" }
    $adb = $cmd.Source
}

$devices = @(& $adb devices | Select-String '^\S+\s+device$')
if ($devices.Count -eq 0) {
    throw "No authorized device. Check the USB cable, board power, and Arduino App Lab."
}

# 重新建立转发（先清掉旧的，避免 "Address already in use"）
& $adb forward --remove "tcp:$LocalPort" 2>$null | Out-Null
& $adb forward "tcp:$LocalPort" "tcp:$RemotePort" | Out-Null

$url = "http://127.0.0.1:$LocalPort/"
try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 8
} catch {
    throw "Forward established but the page failed: $($_.Exception.Message)"
}

# 顺手报一下机器人状态，避免"页面能开但其实断线了"
$status = $null
try { $status = (Invoke-WebRequest -Uri "${url}api/status" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json } catch { }
Write-Host "OK  $url  (HTTP $($r.StatusCode))" -ForegroundColor Green
if ($status -ne $null) {
    Write-Host ("    mode={0}  enabled={1}  servos={2}/15  imu={3}" -f `
        $status.mode, $status.enabled, $status.servo_ids.Count, $status.imu_ok)
}
Write-Host "    note: re-run this script after replugging USB or restarting App Lab"

if (-not $NoBrowser) { Start-Process $url }
