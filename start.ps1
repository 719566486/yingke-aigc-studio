$ErrorActionPreference='Stop'
$StudioRoot=$PSScriptRoot
$StudioPython=Join-Path $StudioRoot '.venv\Scripts\python.exe'
$StudioPid=Join-Path $StudioRoot 'work\server.pid'
$StudioUrl='http://127.0.0.1:8787'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP=Join-Path $StudioRoot 'work'
$env:TMP=$env:TEMP
try {$ready=Invoke-RestMethod "$StudioUrl/api/bootstrap" -TimeoutSec 2} catch {$ready=$null}
if(-not $ready) {
  if(-not(Test-Path -LiteralPath $StudioPython)){throw 'Project Python environment not found.'}
  $process=Start-Process -FilePath $StudioPython -ArgumentList @('-B','run.py') -WorkingDirectory $StudioRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $StudioRoot 'work\server.out.log') -RedirectStandardError (Join-Path $StudioRoot 'work\server.err.log')
  [System.IO.File]::WriteAllText($StudioPid,[string]$process.Id)
  for($attempt=0;$attempt -lt 40;$attempt++){
    Start-Sleep -Milliseconds 500
    try {$ready=Invoke-RestMethod "$StudioUrl/api/bootstrap" -TimeoutSec 1;break} catch {}
    if($process.HasExited){throw 'Server stopped. Check work\server.err.log.'}
  }
  if(-not $ready){throw 'Server not ready. Check work\server.err.log.'}
}
if($env:STUDIO_NO_BROWSER -ne '1'){Start-Process $StudioUrl}
Write-Output "Yingke is ready: $StudioUrl"
