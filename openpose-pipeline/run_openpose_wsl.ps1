param(
    [Parameter(Mandatory = $true)]
    [string]$Video,

    [string]$Name,

    # Optional smoke test:
    # process frames 0 through FrameLast only.
    # Leave as -1 to process the full video.
    [int]$FrameLast = -1,

    # If specified, only write JSON keypoints
    # and skip the labeled overlay video.
    [switch]$JsonOnly
)

$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WindowsPath
    )

    $resolved = [System.IO.Path]::GetFullPath($WindowsPath)

    if ($resolved -match '^([A-Za-z]):\\(.*)$') {
        $drive = $matches[1].ToLower()
        $rest = $matches[2] -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }

    throw "Only local Windows drive paths are supported: $resolved"
}

function Quote-Bash {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    # Safely quote a path/string for bash.
    return "'" + $Value.Replace("'", "'\''") + "'"
}

# ------------------------------------------------------------
# Validate input video
# ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $Video -PathType Leaf)) {
    throw "Video not found: $Video"
}

$VideoPath = (Resolve-Path -LiteralPath $Video).Path

if (-not $Name) {
    $Name = [System.IO.Path]::GetFileNameWithoutExtension($VideoPath)
}

# Make output name filesystem-safe.
$Name = $Name -replace '[<>:"/\\|?*]', '_'

# ------------------------------------------------------------
# Local Windows paths
# ------------------------------------------------------------
#
# Expected script location:
#
#   <repo>\openpose-pipeline\run_openpose.ps1
#
# Expected WSL OpenPose build:
#
#   ~/openpose/build/examples/openpose/openpose.bin
#
# ------------------------------------------------------------

$PipelineRoot = $PSScriptRoot

$OutputDir = Join-Path $PipelineRoot "output\$Name"
$JsonDir = Join-Path $OutputDir "json"
$LabeledVideo = Join-Path $OutputDir "labeled.avi"

# WSL OpenPose installation
$OpenPoseRootLinux = "~/openpose"
$OpenPoseExeLinux = "~/openpose/build/examples/openpose/openpose.bin"
$ModelFolderLinux = "~/openpose/models/"

# ------------------------------------------------------------
# Prepare output directories
# ------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $JsonDir | Out-Null

# Remove old JSON files if this output name was used before.
Get-ChildItem `
    -LiteralPath $JsonDir `
    -Filter "*_keypoints.json" `
    -File `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force

# Remove old overlay video if creating a new one.
if ((-not $JsonOnly) -and (Test-Path -LiteralPath $LabeledVideo)) {
    Remove-Item -LiteralPath $LabeledVideo -Force
}

# ------------------------------------------------------------
# Convert Windows paths into WSL paths
# ------------------------------------------------------------

$VideoWsl = Convert-ToWslPath $VideoPath
$JsonWsl = Convert-ToWslPath $JsonDir
$LabeledWsl = Convert-ToWslPath $LabeledVideo

Write-Host ""
Write-Host "OpenPose GPU pipeline"
Write-Host "---------------------"
Write-Host "Input:     $VideoPath"
Write-Host "Output:    $OutputDir"
Write-Host "WSL build: $OpenPoseExeLinux"
Write-Host ""

# ------------------------------------------------------------
# Verify WSL OpenPose exists
# ------------------------------------------------------------

& wsl.exe bash -lc "test -x $OpenPoseExeLinux"

if ($LASTEXITCODE -ne 0) {
    throw @"
WSL OpenPose executable not found.

Expected:
  ~/openpose/build/examples/openpose/openpose.bin
"@
}

# ------------------------------------------------------------
# Build OpenPose command
# ------------------------------------------------------------

$parts = @(
    $OpenPoseExeLinux
    "--video", (Quote-Bash $VideoWsl)
    "--model_pose", "BODY_25"
    "--model_folder", $ModelFolderLinux
    "--number_people_max", "1"
    "--write_json", (Quote-Bash $JsonWsl)
    "--display", "0"
)

# Optional frame limit.
if ($FrameLast -ge 0) {
    $parts += @(
        "--frame_last",
        $FrameLast.ToString()
    )
}

# JSON-only mode.
if ($JsonOnly) {
    $parts += @(
        "--render_pose",
        "0"
    )
}
else {
    # Save labeled video with BODY_25 overlay.
    $parts += @(
        "--write_video",
        (Quote-Bash $LabeledWsl),
        "--render_pose",
        "2"
    )
}

$command = "cd $OpenPoseRootLinux && " + ($parts -join " ")

# ------------------------------------------------------------
# Run OpenPose inside WSL
# ------------------------------------------------------------

Write-Host "Running OpenPose in WSL..."

if ($FrameLast -ge 0) {
    Write-Host "Processing frames 0-$FrameLast only."
}

Write-Host ""

& wsl.exe bash -lc $command

if ($LASTEXITCODE -ne 0) {
    throw "OpenPose failed with exit code $LASTEXITCODE."
}

# ------------------------------------------------------------
# Print summary
# ------------------------------------------------------------

$jsonCount = @(
    Get-ChildItem `
        -LiteralPath $JsonDir `
        -Filter "*_keypoints.json" `
        -File `
        -ErrorAction SilentlyContinue
).Count

Write-Host ""
Write-Host "OpenPose complete."
Write-Host "JSON frames: $jsonCount"
Write-Host "Keypoints:   $JsonDir"

if (-not $JsonOnly) {
    if (Test-Path -LiteralPath $LabeledVideo) {
        Write-Host "Overlay:     $LabeledVideo"
    }
    else {
        Write-Warning "The expected labeled video was not found."
    }
}