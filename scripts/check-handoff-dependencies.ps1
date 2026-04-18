$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$handoffRoot = Join-Path $repoRoot "handoff"
$matrixPath = Join-Path $handoffRoot "dependency_order_matrix.json"

if (-not (Test-Path $matrixPath)) {
  Write-Error "[check-handoff-dependencies] missing handoff/dependency_order_matrix.json"
}

$requiredRootAssets = @(
  "stage_handoff_catalog.json",
  "integration_matrix.json",
  "validation_rules.json",
  "example_payloads.json"
)

foreach ($asset in $requiredRootAssets) {
  $assetPath = Join-Path $handoffRoot $asset
  if (-not (Test-Path $assetPath)) {
    Write-Error ("[check-handoff-dependencies] missing handoff root asset: {0}" -f $asset)
  }
}

$matrix = Get-Content $matrixPath -Raw | ConvertFrom-Json
if (-not $matrix.sequence) {
  Write-Error "[check-handoff-dependencies] sequence missing in dependency_order_matrix.json"
}

$ids = @{}
$prevTo = $null
foreach ($item in $matrix.sequence) {
  if ($ids.ContainsKey($item.handoff_id)) {
    Write-Error ("[check-handoff-dependencies] duplicate handoff_id: {0}" -f $item.handoff_id)
  }
  $ids[$item.handoff_id] = $true

  if ($item.to_stage -ne ($item.from_stage + 1)) {
    Write-Error ("[check-handoff-dependencies] invalid stage step for {0}" -f $item.handoff_id)
  }
  if ($prevTo -ne $null -and $item.from_stage -ne $prevTo) {
    Write-Error ("[check-handoff-dependencies] non-contiguous order at {0}" -f $item.handoff_id)
  }
  $prevTo = $item.to_stage

  $path = Join-Path $repoRoot $item.path
  if (-not (Test-Path $path)) {
    Write-Error ("[check-handoff-dependencies] missing handoff path: {0}" -f $item.path)
  }
  foreach ($file in $item.required_files) {
    $filePath = Join-Path $path $file
    if (-not (Test-Path $filePath)) {
      Write-Error ("[check-handoff-dependencies] missing file: {0}" -f $filePath)
    }
  }

  $contractPath = Join-Path $path "contract.json"
  if (Test-Path $contractPath) {
    $contract = Get-Content $contractPath -Raw | ConvertFrom-Json
    if ($item.to_stage -le 8 -and -not $contract.consumer_runtime_required_fields) {
      Write-Error ("[check-handoff-dependencies] contract missing consumer_runtime_required_fields: {0}" -f $contractPath)
    }
  }
}

$stageDirs = Get-ChildItem $handoffRoot -Directory | Where-Object { $_.Name -match "^stage\d+_to_stage\d+$" }
foreach ($dir in $stageDirs) {
  if (-not $ids.ContainsKey($dir.Name)) {
    Write-Error ("[check-handoff-dependencies] stage handoff not listed in dependency order: {0}" -f $dir.Name)
  }
}

Write-Host "[check-handoff-dependencies] PASS"
