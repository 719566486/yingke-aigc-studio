$ErrorActionPreference='Stop'
$StudioRoot=$PSScriptRoot
$StudioPid=Join-Path $StudioRoot 'work\server.pid'
if(Test-Path -LiteralPath $StudioPid){
  $StudioProcessId=[int](Get-Content -LiteralPath $StudioPid -Raw)
  $StudioProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$StudioProcessId" -ErrorAction SilentlyContinue
  $expected=Join-Path $StudioRoot '.venv\Scripts\python.exe'
  if($StudioProcess -and $StudioProcess.ExecutablePath -eq $expected -and $StudioProcess.CommandLine -match 'run\.py'){
    Stop-Process -Id $StudioProcessId -Force
    Write-Output 'Yingke server stopped.'
  }elseif($StudioProcess){throw 'Process identity does not match; server was not stopped.'}
  Remove-Item -LiteralPath $StudioPid -Force
}
