param(
    [Parameter(Mandatory = $true)]
    [string]$Video,

    [string]$Name
)

$PipelineRoot = $PSScriptRoot
$OpenPoseExe = Join-Path $PipelineRoot "openpose\bin\OpenPoseDemo.exe"

if (-not (Test-Path $OpenPoseExe)) {
    Write-Error "OpenPose executable not found at: $OpenPoseExe"
    Write-Error "Install the OpenPose Windows binaries into openpose-pipeline\openpose\"
    exit 1
}

$VideoPath = (Resolve-Path $Video).Path

if (-not $Name) {
    $Name = [System.IO.Path]::GetFileNameWithoutExtension($VideoPath)
}

$OutputDir = Join-Path $PipelineRoot "output\$Name"
$JsonDir = Join-Path $OutputDir "json"
$LabeledVideo = Join-Path $OutputDir "labeled.avi"

New-Item -ItemType Directory -Force $JsonDir | Out-Null

Write-Host "Running OpenPose..."
Write-Host "Input:  $VideoPath"
Write-Host "Output: $OutputDir"

& $OpenPoseExe `
    --video $VideoPath `
    --model_pose BODY_25 `
    --number_people_max 1 `
    --write_json $JsonDir `
    --write_video $LabeledVideo `
    --display 0

if ($LASTEXITCODE -ne 0) {
    Write-Error "OpenPose failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "OpenPose complete."
Write-Host "Keypoints: $JsonDir"
Write-Host "Labeled video: $LabeledVideo"