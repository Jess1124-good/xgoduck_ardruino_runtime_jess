# 打开 XGO Duck 上位机网页（双通道：USB / WiFi，自动绕过系统代理）
#
# 背景：
#   1. 板子的 wlan0 会在「手机热点 192.168.43.x」和「校园网 gpnu.edu.cn 10.214.x.x」
#      之间自动切换，写死的书签会失效；
#   2. 本机配了系统代理，Invoke-WebRequest 会被劫持，必须显式绕过；
#   3. adb 有时在断电重启后不恢复，此时只能走 WiFi。
#
# 用法：  powershell -ExecutionPolicy Bypass -File tools\pc-open-web.ps1
#         powershell -ExecutionPolicy Bypass -File tools\pc-open-web.ps1 -NoBrowser
#         powershell -ExecutionPolicy Bypass -File tools\pc-open-web.ps1 -PreferUsb
param(
    [int]$LocalPort = 19527,   # USB 转发用的本机端口（9527 常被 VS Code 占用）
    [int]$RemotePort = 9527,
    [string[]]$BoardHost = @('192.168.43.5', '10.214.173.162'),
    [switch]$PreferUsb,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

# 绕过系统代理：否则访问局域网地址会被发到代理服务器，表现为"超时"
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy

function Get-Status($base) {
    $wc = New-Object System.Net.WebClient
    $wc.Proxy = $null
    return $wc.DownloadString("$base/api/status") | ConvertFrom-Json
}

function Test-Web($base) {
    try { Get-Status $base | Out-Null; return $true } catch { return $false }
}

$adb = "C:\Users\34511\AppData\Local\Arduino15\packages\arduino\tools\adb\32.0.0\adb.exe"
$candidates = @()

# USB 通道：仅当 adb 真的看到设备时才建立转发
if (Test-Path $adb) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $devices = @(& $adb devices 2>&1 | Select-String '^\S+\s+device$')
    if ($devices.Count -gt 0) {
        & $adb forward --remove "tcp:$LocalPort" 2>&1 | Out-Null
        & $adb forward "tcp:$LocalPort" "tcp:$RemotePort" 2>&1 | Out-Null
        $candidates += "http://127.0.0.1:$LocalPort"
    }
    $ErrorActionPreference = $prevEap
}

foreach ($h in $BoardHost) { $candidates += "http://${h}:$RemotePort" }

# 默认先试 USB，失败再试 WiFi；-PreferUsb 只是把顺序写死，两者都会尝试
if (-not $PreferUsb) { $candidates = @($candidates | Sort-Object { $_ -like '*127.0.0.1*' }) }

$picked = $null
foreach ($c in $candidates) {
    if (Test-Web $c) { $picked = $c; break }
}

if (-not $picked) {
    Write-Host "没找到可用的板子地址。已尝试：" -ForegroundColor Red
    $candidates | ForEach-Object { Write-Host "  $_" }
    Write-Host "检查：板子是否上电、是否和电脑在同一个 WiFi、App 是否在 App Lab 里启动。"
    exit 1
}

$status = Get-Status $picked
Write-Host "OK  $picked/" -ForegroundColor Green
Write-Host ("    mode={0}  enabled={1}  servos={2}/15  imu={3}  fb={4} Hz" -f `
    $status.mode, $status.enabled, $status.servo_ids.Count, $status.imu_ok, [math]::Round($status.feedback_hz,1))
Write-Host "    note: re-run after replugging USB or switching WiFi"

if (-not $NoBrowser) { Start-Process "$picked/" }
