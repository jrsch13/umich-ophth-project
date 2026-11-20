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