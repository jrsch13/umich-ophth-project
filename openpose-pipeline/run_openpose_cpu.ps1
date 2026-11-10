param(
    [Parameter(Mandatory = $true)]
    [string]$Video,

    [string]$Name,

    [string]$OutputDir,

    [string]$LabeledVideoPath,

    [int]$FrameLast = -1,

    [switch]$JsonOnly
)

$ErrorActionPreference = "Stop"

$PipelineRoot = $PSScriptRoot

$OpenPoseExe = Join-Path `
    $PipelineRoot `
    "openpose\bin\OpenPoseDemo.exe"

$ModelFolder = Join-Path `
    $PipelineRoot `
    "openpose\models"

# ------------------------------------------------------------
# Validate OpenPose
# ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $OpenPoseExe)) {
    throw "CPU OpenPose executable not found: $OpenPoseExe"
}

if (-not (Test-Path -LiteralPath $ModelFolder)) {
    throw "OpenPose model folder not found: $ModelFolder"
}

$Body25Model = Join-Path `
    $ModelFolder `
    "pose\body_25\pose_iter_584000.caffemodel"

if (-not (Test-Path -LiteralPath $Body25Model)) {
    throw "BODY_25 model not found: $Body25Model"
}

# ------------------------------------------------------------
# Resolve input
# ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $Video -PathType Leaf)) {
    throw "Video not found: $Video"
}

$VideoPath = (Resolve-Path -LiteralPath $Video).Path

if (-not $Name) {
    $Name = [System.IO.Path]::GetFileNameWithoutExtension($VideoPath)
}

$Name = $Name -replace '[<>:"/\\|?*]', '_'

# ------------------------------------------------------------
# Output paths
# ------------------------------------------------------------

if (-not $OutputDir) {
    $OutputDir = Join-Path `
        $PipelineRoot `
        "output\$Name"
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

$JsonDir = Join-Path $OutputDir "json"

if ($LabeledVideoPath) {
    $LabeledVideo = [System.IO.Path]::GetFullPath(
        $LabeledVideoPath
    )
}
else {
    $LabeledVideo = Join-Path `
        $OutputDir `
        "labeled.avi"
}

New-Item `
    -ItemType Directory `
    -Force `
    -Path $JsonDir |
    Out-Null

if (-not $JsonOnly) {

    $LabeledParent = Split-Path `
        -Parent `
        $LabeledVideo

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $LabeledParent |
        Out-Null
}

# Remove stale output from an earlier run.

Get-ChildItem `
    -LiteralPath $JsonDir `
    -Filter "*_keypoints.json" `
    -File `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force

if (
    (-not $JsonOnly) -and
    (Test-Path -LiteralPath $LabeledVideo)
) {
    Remove-Item `
        -LiteralPath $LabeledVideo `
        -Force
}

# ------------------------------------------------------------
# OpenPose arguments
# ------------------------------------------------------------

$Arguments = @(
    "--video"
    $VideoPath

    "--model_pose"
    "BODY_25"

    "--model_folder"
    $ModelFolder

    "--number_people_max"
    "1"

    "--write_json"
    $JsonDir

    "--display"
    "0"
)

if ($FrameLast -ge 0) {

    $Arguments += @(
        "--frame_last"
        $FrameLast.ToString()
    )
}

if ($JsonOnly) {

    $Arguments += @(
        "--render_pose"
        "0"
    )
}
else {

    $Arguments += @(
        "--write_video"
        $LabeledVideo

        # CPU rendering
        "--render_pose"
        "1"
    )
}

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------

Write-Host ""
Write-Host "OpenPose CPU pipeline"
Write-Host "---------------------"
Write-Host "Input:  $VideoPath"
Write-Host "Output: $OutputDir"
Write-Host ""

& $OpenPoseExe @Arguments

if ($LASTEXITCODE -ne 0) {
    throw "OpenPose failed with exit code $LASTEXITCODE."
}

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

$JsonCount = @(
    Get-ChildItem `
        -LiteralPath $JsonDir `
        -Filter "*_keypoints.json" `
        -File `
        -ErrorAction SilentlyContinue
).Count

Write-Host ""
Write-Host "OpenPose complete."
Write-Host "JSON frames: $JsonCount"
Write-Host "Keypoints:   $JsonDir"

if (-not $JsonOnly) {

    if (Test-Path -LiteralPath $LabeledVideo) {
        Write-Host "Overlay:     $LabeledVideo"
    }
    else {
        Write-Warning `
            "Expected labeled video was not found."
    }
}