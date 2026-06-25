$ErrorActionPreference = "Stop"

Write-Host "== Reddit Pain Radar smoke test =="

if (!(Test-Path "pain_radar.py") -or !(Test-Path "src\agent_memory.py")) {
    throw "Run this script from the repo root."
}

$python = ".\.venv\Scripts\python.exe"
if (!(Test-Path $python)) {
    $python = ".\.venv\Scripts\python"
}
if (!(Test-Path $python)) {
    throw "Python virtualenv not found at .\.venv\Scripts\python.exe"
}

Write-Host "`n== Compile check =="
& $python -m py_compile pain_radar.py src\agent_memory.py src\report_writer.py src\pain_scorer.py src\rss_fetcher.py src\weekly_summary.py

Write-Host "`n== Memory stats =="
& $python pain_radar.py --memory-stats

Write-Host "`n== Memory health =="
& $python pain_radar.py --memory-health

Write-Host "`n== Review queue default =="
& $python pain_radar.py --memory-review-queue --limit 3

Write-Host "`n== Review queue all statuses =="
& $python pain_radar.py --memory-review-queue --status all --limit 3

Write-Host "`n== Memory search =="
& $python pain_radar.py --memory-search "workflow pain automation"

Write-Host "`nSmoke test passed."
