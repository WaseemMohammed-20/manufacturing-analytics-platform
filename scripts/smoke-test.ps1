$ErrorActionPreference = 'Stop'

function Get-ApiJson {
    param([string]$Path)
    Invoke-RestMethod -Uri "http://localhost:8000$Path" -Method Get
}

$health = Get-ApiJson '/health'
if ($health.status -ne 'ok' -or $health.database -ne 'connected') {
    throw 'API health check did not confirm PostgreSQL connectivity.'
}

$kpis = Get-ApiJson '/api/dashboard/kpis'
$downtime = Get-ApiJson '/api/dashboard/downtime'
$defects = Get-ApiJson '/api/dashboard/defects'
$machines = Get-ApiJson '/api/machines'
$alerts = Get-ApiJson '/api/alerts'
$thresholds = Get-ApiJson '/api/alert-thresholds'

$oeeFromComponents = $kpis.availability * $kpis.performance * $kpis.quality
if ([math]::Abs($kpis.oee - $oeeFromComponents) -gt 0.0000000001) {
    throw 'OEE does not reconcile with availability, performance, and quality.'
}
if ($kpis.total_produced -le 0 -or $machines.Count -eq 0 -or $downtime.Count -eq 0) {
    throw 'Expected seeded PostgreSQL records are missing.'
}
$expectedDefectRate = $defects.total_defects / $kpis.total_produced
if ([math]::Abs($defects.defect_rate - $expectedDefectRate) -gt 0.0000000001) {
    throw 'Defect rate does not reconcile with defect and production counts.'
}
if ($thresholds.Count -lt 2 -or @($alerts | Where-Object machine_id -eq 20).Count -eq 0) {
    throw 'Persisted thresholds or the seeded CNC-20 alert are missing.'
}

$dashboard = Invoke-WebRequest -UseBasicParsing http://localhost:8080/
$superset = Invoke-WebRequest -UseBasicParsing http://localhost:8088/health
if ($dashboard.StatusCode -ne 200 -or $superset.StatusCode -ne 200) {
    throw 'Frontend or Superset health endpoint did not return HTTP 200.'
}

Write-Output ('Smoke test passed: 7 API routes, frontend, Superset; {0} machines, {1} produced, {2} active alerts.' -f $machines.Count, $kpis.total_produced, $alerts.Count)