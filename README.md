# UMich Ophthalmology Anipose Pipeline

## Purpose of the Project

This repository supports development of a computer vision pipeline for ergonomic assessment in ophthalmology.

The broader research goal is to use video-based pose estimation to quantify working postures and compensatory movements that may be associated with musculoskeletal injury risk during ophthalmology tasks.

The current focus of this repository is narrower:

- build a reproducible **Anipose + DeepLabCut 2D pose-estimation pipeline**;
- test whether generic human pose landmarks are usable on ophthalmology training videos;
- develop and evaluate heuristics for:
  - **shoulder hiking**;
  - **neck extension**;
- identify where a future custom pose model or 3D Anipose pipeline would improve measurement quality.

The current pipeline should be treated as a **research prototype**, not as a validated clinical or ergonomic measurement system.

---

# What This Repository Is Trying to Accomplish

The present workflow is:

1.) ophthalmology video
2.) DeepLabCut human pose model
3.) Raw 2D landmark coordinates + likelihoods
4.) Anipose 2D filtering
5.) Labeled video for visual inspection
6.) Pipeline QC / heuristic tester
7.) Shoulder-hiking and neck-extension proxy metrics

---

# Repository Structure

A typical repository layout is:

```text
umich-ophth-anipose/
│
├── .gitignore
├── README.md
├── requirements.txt
├── setup_baseline_model.py
├── testing.ipynb
│
├── data/
│   └── raw-videos/
│       └── ...
│
├── models/
│   └── ophtho-baseline-human-Jason-YYYY-MM-DD/
│       ├── config.yaml
│       ├── dlc-models/
│       ├── labeled-data/
│       ├── training-datasets/
│       └── videos/
│
└── anipose-pipeline-v1/
    ├── config.toml
    │
    ├── scripts/
    │   └── evaluate_pipeline_v1.py
    │
    └── sample01/
        ├── videos-raw/
        │   └── side_profile_test.MOV
        │
        ├── pose-2d/
        │   └── side_profile_test.h5
        │
        ├── pose-2d-filtered/
        │   └── side_profile_test.h5
        │
        └── videos-labeled-filtered/
            └── side_profile_test.mp4
```

## Important folder roles

### `data/`

Stores original research data or references to it.

Raw participant/research videos should generally **not be committed to GitHub**, they are way too big and the push will fail.

### `models/`

Stores DeepLabCut projects and downloaded/trained model weights.

These files can be hundreds of MB and should generally be excluded from normal Git tracking.

### `anipose-pipeline-v1/`

Contains one reproducible version of the Anipose pipeline.

Each major pipeline version should have its own:

```text
config.toml
scripts/
output folders
```

For example:

```text
anipose-pipeline-v1/
anipose-pipeline-v2/
anipose-pipeline-v3/
```

The configuration used to produce a result should remain associated with that pipeline version.

---

# Environment Setup

The current baseline was developed using a Conda environment, make sure to use Python 3.10.

Example:

```powershell
conda create -n ophtho-anipose python=3.10
conda activate ophtho-anipose
```

Install Anipose and DeepLabCut/TensorFlow dependencies as needed.

The current tested environment includes:

```text
Python 3.10
DeepLabCut 3.0.2
TensorFlow 2.15.1
```

FFmpeg and ffprobe must also be available on the system PATH for labeled-video generation.

Verify:

```powershell
ffmpeg -version
ffprobe -version
```

---

# Creating the Baseline DeepLabCut Model Project

The baseline uses DeepLabCut's pretrained `full_human` model.

The helper script:

```text
setup_baseline_model.py
```

creates a DeepLabCut project under:

```text
models/
```

and downloads the pretrained model weights.

Run from the repository root:

```powershell
conda activate ophtho-anipose
python .\setup_baseline_model.py
```

After successful setup, the model directory should contain a DeepLabCut project similar to:

```text
models/
└── ophtho-baseline-human-Jason-YYYY-MM-DD/
    ├── config.yaml
    └── dlc-models/
```

The Anipose pipeline's `config.toml` should point `model_folder` to this project directory. There is a line at the top of config.toml that has a variable for model_folder

Example:

```toml
model_folder = "C:/Users/USERNAME/Documents/umich-ophth-anipose/models/ophtho-baseline-human-Jason-YYYY-MM-DD"
```

Use forward slashes in Windows paths inside TOML strings.

---

# Creating a New Pipeline

A pipeline version should be self-contained.

For example:

```text
anipose-pipeline-v2/
├── config.toml
├── scripts/
└── sample01/
    └── videos-raw/
```

To create a new version:

1. Copy the previous pipeline folder or create a new empty pipeline directory.
2. Give the new version its own `config.toml`.
3. Put one or more test sessions under the pipeline directory.
4. Each session should contain a `videos-raw/` directory.
5. Change only the parameters being tested.
6. Keep notes on what distinguishes each version.

Example:

```text
anipose-pipeline-v2/
├── config.toml
└── sample01/
    └── videos-raw/
        └── test_video.MOV
```

---

# Example `config.toml`

The config.toml in anipose-pipepline-v1/ has comments for the different settings that can be included in a 2D configuration.

A minimal 2D configuration can look like:

```toml
project = "ophtho-anipose-v1"

model_folder = "C:/Users/USERNAME/Documents/umich-ophth-anipose/models/ophtho-baseline-human-Jason-YYYY-MM-DD"

nesting = 1

video_extension = "MOV"

[pipeline]
videos_raw = "videos-raw"

[filter]
enabled = true
type = "medfilt"
medfilt = 13
offset_threshold = 25
score_threshold = 0.8
spline = false

[labeling]
scheme = [
    ["shoulder1", "shoulder2"],
    ["shoulder1", "hip1"],
    ["shoulder2", "hip2"],
    ["hip1", "hip2"],
    ["shoulder1", "elbow1", "wrist1"],
    ["shoulder2", "elbow2", "wrist2"],
    ["chin", "forehead"]
]
```

The exact `video_extension` must match the input files OR ELSE ANIPOSE WILL CRASH

Our example videos or .MOV so this needs to be included:

```toml
video_extension = "MOV"
```

---

# Running Anipose on a Pipeline

Navigate into the pipeline directory containing `config.toml`.

Example:

```powershell
cd "C:\Users\USERNAME\Documents\umich-ophth-anipose\anipose-pipeline-v1"
```

Activate the environment:

```powershell
conda activate ophtho-anipose
```

## 1. Run 2D pose estimation

```powershell
anipose analyze
```

Expected output:

```text
sample01/
└── pose-2d/
    └── side_profile_test.h5
```

This `.h5` file contains the raw DeepLabCut landmark estimates.

For each bodypart and frame, the file contains approximately:

```text
x
y
likelihood
```

## 2. Run Anipose filtering

```powershell
anipose filter
```

Expected output:

```text
sample01/
└── pose-2d-filtered/
    └── side_profile_test.h5
```

If the filtering configuration changes, delete the existing filtered `.h5` before rerunning so the output is regenerated.

Example:

```powershell
Remove-Item ".\sample01\pose-2d-filtered\side_profile_test.h5"
anipose filter
```

The raw `pose-2d` file does not need to be regenerated unless pose inference itself changes.

## 3. Generate a labeled video

```powershell
anipose label-2d-filter
```

Expected output:

```text
sample01/
└── videos-labeled-filtered/
    └── side_profile_test.mp4
```

This is the most important first visual quality control step to visually confirm that the pose-tracking output is actually tracking the person correctly.

Watch the side_profile_test.mp4 video and check if the landmarks stay attached to the correct body part, jump to background people/objects/equipment, disappear during occlusion, and follow the intended movement correctly.

---

# Testing the Pipeline

The script scripts/evaluate_pipeline_v1.py is designed to test both **pose-estimation pipeline** and **current heuristics**.

Run this:

```powershell
python .\scripts\evaluate_pipeline_v1.py `
  --video ".\sample01\videos-raw\side_profile_test.MOV" `
  --raw ".\sample01\pose-2d\side_profile_test.h5" `
  --filtered ".\sample01\pose-2d-filtered\side_profile_test.h5" `
  --baseline-start 45 `
  --baseline-end 50 `
  --shoulder shoulder1 `
  --hip hip1 `
  --chin chin
```

where:
--video is the path to the original video
--raw is the path to the raw DeepLabCut 2D pose .h5
--filtered is the path to Anipose's filtered .h5
--baseline-start is the start of the neutral/reference posture, in seconds
--baseline-end is the end of the neutral/reference posture; the baseline interval should correspond to a visually confirmed neutral/reference posture.
--shoulder is the landmark used as the shoulder, shoulder1 looked like the more reliable visible shoulder in the side-view video, you can use shoulder2 or a custom landmark if another shoulder is better
--hip and --chin -> same as shoulder

If a known movement occurs during a specific interval, also provide:

```powershell
--action-start 55 `
--action-end 60
```

The tester writes:

```text
pipeline_test_results/
├── pipeline_qc.csv
├── heuristics_timeseries.csv
├── interval_stats.csv
├── shoulder_hike_proxy.png
└── neck_extension_proxy.png
```

---

# How the Pipeline Tester Works

The tester has two separate jobs:

## 1. Pipeline Quality Control

For each landmark, DeepLabCut produces:

```text
x
y
likelihood
```

Example:

```text
shoulder1
x = 612.4
y = 337.8
likelihood = 0.96
```

The `likelihood` is the pose model's confidence score for that predicted landmark. It is **not** the heuristic and should not be interpreted literally as a calibrated probability that the landmark is anatomically correct.

The tester summarizes values such as:

```text
median likelihood
percentage of frames below the confidence threshold
percentage of missing coordinates
percentage of out-of-frame coordinates
```

The default confidence threshold is 0.80, and a prediction below this threshold is rejected before it is used by the heuristic. The tester also rejects coordinates that fall outside the actual video dimensions.

---

# Landmark Cleaning Before the Heuristic

The heuristic is calculated from the **raw DeepLabCut detections**, not from the Anipose-filtered coordinates because the Anipose-filtered file had already shown that it could introduce artificial motion (possibly from people moving in the background), and we don't want the heuristic measuring artifacts created by the filter instead of the ophthalmologist’s actual movement. **planning on testing this with spline = False in v2**

The current cleaning procedure is:

raw x/y/likelihood -> likelihood >= 0.8? -> coordinate inside image? -> keep valid point -> linearly interpolate only short missing gaps -> heuristic

By default, only missing gaps of up to 5 frames are interpolated. Long low-confidence periods remain missing rather than being fabricated. This is important because earlier testing (in pipeline-v1) showed that cubic spline interpolation could produce extremely large, physically impossible coordinates across long gaps. 

---

# Shoulder-Hiking Heuristic

The current shoulder-hiking metric is a **2D proxy**.

It uses:

```text
shoulder1
hip1
```

For every frame, define the torso vector:

```math
T(t) = Shoulder(t) - Hip(t)
```

A neutral/reference interval is selected from the video, and the median torso direction during that interval defines a unit vector pointing along the subject's neutral torso axis:

```math
\hat{u}_{neutral}
```

The current shoulder-to-hip displacement is projected onto this neutral torso axis:

```math
P(t) = (Shoulder(t) - Hip(t)) \cdot \hat{u}_{neutral}
```

The neutral baseline is:

```math
P_{neutral} = median(P(t))
```

during the reference interval.

The shoulder-hiking proxy is then:

```math
ShoulderHike(t) = P(t) - P_{neutral}
```

Positive values mean that the shoulder has moved farther upward along the reference torso axis.

## Normalized shoulder-hiking metric

Pixel values depend on camera distance, image resolution, and participant size.

The tester therefore also normalizes shoulder displacement by the neutral torso length:

```math
ShoulderHike_{norm}(t)
=
100 \times
\frac{ShoulderHike(t)}
{TorsoLength_{neutral}}
```

The primary output is:

```text
shoulder_hike_proxy_pct_torso
```

Example interpretation:

```text
0%      approximately neutral
+4%     shoulder elevated by approximately 4% of baseline torso length
```

This is not yet a validated anatomical shoulder-elevation measurement.

---

# Neck-Extension Heuristic

The current neck-extension metric is also a **2D side-view proxy**.

It uses:

```text
hip1
shoulder1
chin
```

Two vectors are created:

Torso vector:

```math
T = Shoulder - Hip
```

Head/neck proxy vector:

```math
N = Chin - Shoulder
```

The signed angle between these vectors is calculated:

```math
\theta(t)
=
atan2(
T_x N_y - T_y N_x,
T_x N_x + T_y N_y
)
```

The median angle during the neutral reference interval is:

```math
\theta_{neutral}
```

The final metric is:

```math
NeckExtension(t)
=
\theta(t) - \theta_{neutral}
```

The result is expressed in degrees.

Ideally:

```text
0°      neutral/reference posture
+value  extension
-value  flexion
```

Depending on which side of the subject the camera views, the sign may be reversed.

The tester supports:

```powershell
--neck-sign -1
```

to flip the sign if necessary.

---

# Suggested Development Workflow


1. Get one video through Anipose
2. Inspect the labeled video
3. Evaluate landmark likelihoods
4. Select neutral and known-action intervals
5. Run evaluate_pipeline_v1.py
6. Inspect heuristic plots and QC
7. Revise heuristic
8. Test on additional videos/participants
9. Create the next pipeline/model version

---

# Git / Data Management

Do not commit large model weights or raw research videos to normal Git history.

Recommended `.gitignore` entries include:

```gitignore
# DeepLabCut model projects / weights
models/

# Raw videos
data/raw-videos/
**/videos-raw/

# Generated Anipose outputs
**/pose-2d/
**/pose-2d-filtered/
**/pose-3d/
**/videos-labeled/
**/videos-labeled-filtered/

# Video files
*.MOV
*.mov
*.mp4
*.avi

# Python
__pycache__/
*.pyc
```

Files that should normally remain under version control include:

```text
README.md
requirements.txt
setup_baseline_model.py
config.toml
scripts/
.gitignore
```

---
