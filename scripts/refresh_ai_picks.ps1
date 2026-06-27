# AI 荐股定时刷新 —— 由 Windows 计划任务调用（午盘 11:35 / 收盘后 15:05）
# 触发时段由后端按当前时间自动判定(midday / close)，此处只负责强制刷新。
# 后端地址固定 127.0.0.1:8000；不在交易日则后端会自行归到下一交易日。

$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8000'
$logDir = Join-Path $PSScriptRoot '..\data\logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = Join-Path $logDir 'ai_picks_cron.log'

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
}

# 周末不跑（交易日才有意义）
if ((Get-Date).DayOfWeek -in 'Saturday','Sunday') {
    Write-Log 'SKIP weekend'
    return
}

# 1) 健康探活：后端没起就记一笔退出，不报错
try {
    Invoke-RestMethod -Uri "$base/api/system/health" -TimeoutSec 10 | Out-Null
} catch {
    Write-Log "SKIP backend down: $($_.Exception.Message)"
    return
}

# 2) 强制刷新当前时段 —— 两个策略都刷(动能买点 momentum / 普林格KST周期 pring)
foreach ($strategy in @('momentum', 'pring')) {
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$base/api/ai-picks/refresh?force=true&strategy=$strategy" -TimeoutSec 30
        Write-Log "refresh[$strategy] -> status=$($r.status) msg=$($r.message)"
    } catch {
        Write-Log "ERROR refresh[$strategy] failed: $($_.Exception.Message)"
    }
}
