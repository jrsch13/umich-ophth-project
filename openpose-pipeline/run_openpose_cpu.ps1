
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
}