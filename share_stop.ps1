$ErrorActionPreference='Stop'
$StudioRoot=$PSScriptRoot
$statePath=Join-Path $StudioRoot 'data\sharing-state.json'
[System.IO.File]::WriteAllText((Join-Path $StudioRoot 'work\share-stop'),'stop')
if(Test-Path -LiteralPath $statePath){
  $state=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($state.tunnel_pid){
    $owned=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.tunnel_pid)" -ErrorAction SilentlyContinue
    $knownSsh=$owned -and $owned.Name -eq 'ssh.exe' -and $owned.CommandLine -match 'localhost\.run'
    $knownCloud=$owned -and $owned.Name -eq 'cloudflared.exe' -and $owned.ExecutablePath -eq (Join-Path $StudioRoot 'work\tools\cloudflared.exe')
    if(($knownSsh -or $knownCloud) -and $owned.CommandLine -match '8788'){
      Stop-Process -Id $state.tunnel_pid -Force -ErrorAction SilentlyContinue
    }
  }
  if($state.gateway_pid){
    $gateway=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.gateway_pid)" -ErrorAction SilentlyContinue
    if($gateway -and $gateway.Name -like 'python*' -and $gateway.CommandLine -match 'run_share\.py'){
      Stop-Process -Id $state.gateway_pid -Force -ErrorAction SilentlyContinue
    }
  }
}
Write-Output 'Public sharing is stopping. The administrator studio remains local.'
