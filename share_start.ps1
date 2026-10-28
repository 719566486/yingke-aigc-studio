$ErrorActionPreference='Stop'
$StudioRoot=$PSScriptRoot
$CloudState=Join-Path $StudioRoot 'data\cloud-deployment.json'
if(Test-Path -LiteralPath $CloudState){
  $Cloud=Get-Content -LiteralPath $CloudState -Raw -Encoding UTF8 | ConvertFrom-Json
  if($Cloud.ready){
    Write-Output 'The verified cloud studio is active. This computer can be turned off.'
    Write-Output 'Entry: https://719566486.github.io/yingke-aigc-studio/'
    if($env:STUDIO_NO_BROWSER -ne '1'){Start-Process 'https://719566486.github.io/yingke-aigc-studio/'}
    return
  }
}
$StudioPid=Join-Path $StudioRoot 'work\share-supervisor.pid'
$StudioPython=Join-Path $StudioRoot '.venv\Scripts\python.exe'
$StudioScript=Join-Path $StudioRoot 'deploy\share_runner.py'
$running=$false
if(Test-Path -LiteralPath $StudioPid){
  $savedId=[int](Get-Content -LiteralPath $StudioPid -Raw)
  $saved=Get-CimInstance Win32_Process -Filter "ProcessId=$savedId" -ErrorAction SilentlyContinue
  $running=$saved -and $saved.Name -like 'python*' -and $saved.CommandLine -match [Regex]::Escape($StudioScript)
}
if(-not $running){
  $env:TEMP=Join-Path $StudioRoot 'work'
  $env:TMP=$env:TEMP
  $env:PYTHONIOENCODING='utf-8'
  $env:PYTHONDONTWRITEBYTECODE='1'
  Start-Process -FilePath $StudioPython -ArgumentList @('-B',('"'+$StudioScript+'"')) -WorkingDirectory $StudioRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $StudioRoot 'work\share-supervisor.out.log') -RedirectStandardError (Join-Path $StudioRoot 'work\share-supervisor.err.log') | Out-Null
}
Write-Output 'Sharing is starting. Keep this computer awake.'
Write-Output 'Entry: https://719566486.github.io/yingke-aigc-studio/'
if($env:STUDIO_NO_BROWSER -ne '1'){Start-Process 'https://719566486.github.io/yingke-aigc-studio/'}
