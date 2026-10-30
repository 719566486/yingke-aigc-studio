$ErrorActionPreference='Stop'
$StudioRoot=Split-Path -Parent $PSScriptRoot
$env:STUDIO_NO_BROWSER='1'
# Run inside Task Scheduler, independently of the editor or chat process tree.
while($true){
  try{
    if(-not(Test-Path -LiteralPath (Join-Path $StudioRoot 'work\share-stop'))){
      & (Join-Path $StudioRoot 'share_start.ps1') | Out-Null
    }
  }catch{
    Add-Content -LiteralPath (Join-Path $StudioRoot 'work\keep-alive.log') -Encoding UTF8 -Value 'Sharing check failed; retrying in 30 seconds.'
  }
  Start-Sleep -Seconds 30
}
