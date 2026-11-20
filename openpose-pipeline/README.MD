# OpenPose Pipeline

This directory contains the OpenPose BODY_25 inference wrappers used by the ophthalmology ergonomic training project.

OpenPose itself is **not committed to this repository** because the binaries, dependencies, model weights, and generated outputs are large.

After cloning the repository, each workstation must install an OpenPose runtime locally.

Two supported project workflows currently exist:

```text
CPU workstation
    ↓
run_openpose_cpu.ps1
    ↓
native Windows OpenPose CPU build

NVIDIA GPU workstation
    ↓
run_openpose_wsl.ps1
    ↓
WSL2 + CUDA + source-built OpenPose
```

Both wrappers produce the same output format so downstream session-analysis code does not need to care which backend was used.

---

# Repository Layout

Expected structure:

```text
openpose-pipeline/
├── README.MD
├── run_openpose_cpu.ps1
├── run_openpose_wsl.ps1
├── run_openpose.ps1
│
├── openpose/              # local Windows CPU install; gitignored
│   ├── bin/
│   └── models/
│
└── output/                # generated test output; gitignored
```

The `openpose/` directory is only required for the native Windows CPU workflow.

The WSL GPU workflow installs OpenPose separately inside Linux at:

```text
~/openpose
```

---

# Which Backend Should I Use?

## CPU

Use:

```text
run_openpose_cpu.ps1
```

when:

- the machine does not have a compatible NVIDIA GPU;
- you want the simplest Windows setup;
- you are testing application integration;
- processing speed is not critical.

CPU OpenPose can be very slow.

---

## NVIDIA GPU

Use:

```text
run_openpose_wsl.ps1
```

when:

- the workstation has a supported NVIDIA GPU;
- WSL2 GPU passthrough is available;
- OpenPose has been compiled for that GPU architecture.

This is the preferred high-performance workflow for the resident training station.

---

# Clone the Repository

From Windows PowerShell:

```powershell
git clone https://github.com/jrsch13/umich-ophth-project.git
cd umich-ophth-project
```

---

# CPU Setup

## 1. Download the Windows CPU OpenPose Build

Download the OpenPose v1.7.0 Windows CPU portable package.

The package name is similar to:

```text
openpose-1.7.0-binaries-win64-cpu-python3.7-flir-3d.zip
```

Extract the contents so this executable exists:

```text
openpose-pipeline/
└── openpose/
    └── bin/
        └── OpenPoseDemo.exe
```

Verify from the repository root:

```powershell
Test-Path ".\openpose-pipeline\openpose\bin\OpenPoseDemo.exe"
```

Expected:

```text
True
```

---

## 2. Install BODY_25 Model Files

The CPU build requires BODY_25 model files under:

```text
openpose-pipeline/
└── openpose/
    └── models/
        └── pose/
            └── body_25/
                ├── pose_deploy.prototxt
                └── pose_iter_584000.caffemodel
```

Verify:

```powershell
Test-Path ".\openpose-pipeline\openpose\models\pose\body_25\pose_deploy.prototxt"

Test-Path ".\openpose-pipeline\openpose\models\pose\body_25\pose_iter_584000.caffemodel"
```

Both should return:

```text
True
```

The model weights are not committed to Git.

If the bundled OpenPose model downloader fails, copy the BODY_25 files from a known working OpenPose installation or another approved project source.

---

# Test the CPU Pipeline

From the repository root:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video "C:\path\to\video.mp4" `
  -FrameLast 100
```

`-FrameLast 100` processes frames 0 through 100 and is strongly recommended for the first test because CPU inference is slow.

Example:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video "C:\Users\YourName\Downloads\Side_shortened.mp4" `
  -FrameLast 100
```

Expected output:

```text
openpose-pipeline/
└── output/
    └── Side_shortened/
        ├── labeled.avi
        └── json/
            ├── ..._000000000000_keypoints.json
            ├── ..._000000000001_keypoints.json
            └── ...
```

If approximately 101 JSON files are created and `labeled.avi` shows the BODY_25 skeleton overlay, the CPU pipeline is working.

---

# NVIDIA GPU / WSL Setup

The tested GPU workflow uses:

```text
Windows
+
WSL2
+
Ubuntu 22.04
+
NVIDIA Windows driver
+
CUDA Toolkit inside WSL
+
OpenPose compiled from source
```

The development GPU workstation uses an RTX 5070.

---

# 1. Install WSL2

Open PowerShell as Administrator:

```powershell
wsl.exe --install -d Ubuntu-22.04
wsl --update
```

Restart Windows if requested.

Confirm the distribution is using WSL2:

```powershell
wsl -l -v
```

Launch Ubuntu:

```powershell
wsl
```

---

# 2. Verify NVIDIA GPU Access

Inside WSL:

```bash
nvidia-smi
```

You should see the installed NVIDIA GPU.

If `nvidia-smi` does not work, stop here and fix Windows NVIDIA driver / WSL GPU access before continuing.

Do not install a separate Linux NVIDIA display driver inside WSL.

---

# 3. Install CUDA Toolkit Inside WSL

The RTX 5070 setup has been tested using CUDA 12.8.

Inside WSL:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb

sudo dpkg -i cuda-keyring_1.1-1_all.deb

sudo apt update

sudo apt install -y cuda-toolkit-12-8
```

Add CUDA to the shell environment:

```bash
echo 'export PATH=/usr/local/cuda-12.8/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.8/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc

source ~/.bashrc
```

Verify:

```bash
nvcc --version
```

and:

```bash
nvidia-smi
```

---

# 4. Install OpenPose Build Dependencies

Inside WSL:

```bash
sudo apt update

sudo apt install -y \
  build-essential \
  cmake \
  git \
  pkg-config \
  libopencv-dev \
  libgoogle-glog-dev \
  libgflags-dev \
  libprotobuf-dev \
  protobuf-compiler \
  libboost-all-dev \
  libhdf5-dev \
  libatlas-base-dev \
  libleveldb-dev \
  libsnappy-dev \
  liblmdb-dev
```

Verify:

```bash
cmake --version
```

---

# 5. Clone OpenPose Inside WSL

```bash
cd ~

git clone https://github.com/CMU-Perceptual-Computing-Lab/openpose.git

cd openpose

git submodule update --init --recursive --remote
```

The expected source location is:

```text
~/openpose
```

---

# 6. Install BODY_25 Model Files

The WSL OpenPose build expects:

```text
~/openpose/models/pose/body_25/
```

containing:

```text
pose_deploy.prototxt
pose_iter_584000.caffemodel
```

Create the directory if necessary:

```bash
mkdir -p ~/openpose/models/pose/body_25
```

If BODY_25 is already installed in the Windows CPU OpenPose directory, copy it into WSL.

Example:

```bash
cp -r \
  "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-project/openpose-pipeline/openpose/models/pose/body_25/"* \
  ~/openpose/models/pose/body_25/
```

Verify:

```bash
ls -lh ~/openpose/models/pose/body_25/
```

---

# 7. Build OpenPose for the NVIDIA GPU

Create a clean build directory:

```bash
cd ~/openpose

rm -rf build
mkdir build
cd build
```

## RTX 5070

The RTX 5070 uses compute capability 12.0 / `sm_120`.

Configure:

```bash
cmake .. \
  -DGPU_MODE=CUDA \
  -DUSE_CUDNN=OFF \
  -DCUDA_ARCH=Manual \
  -DCUDA_ARCH_BIN=120 \
  -DCUDA_ARCH_PTX=120 \
  -DDOWNLOAD_BODY_25_MODEL=OFF \
  -DDOWNLOAD_FACE_MODEL=OFF \
  -DDOWNLOAD_HAND_MODEL=OFF \
  -DCMAKE_BUILD_TYPE=Release
```

Do **not** blindly use architecture `120` for another NVIDIA GPU.

Other GPUs may require a different CUDA architecture value.

Build:

```bash
make -j$(nproc)
```

Verify:

```bash
ls ~/openpose/build/examples/openpose/openpose.bin
```

Expected:

```text
~/openpose/build/examples/openpose/openpose.bin
```

---

# Test OpenPose Directly in WSL

This is optional but useful before testing the Windows wrapper.

Create an output directory first:

```bash
mkdir -p \
  "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-project/openpose-pipeline/output/test/json"
```

Then:

```bash
cd ~/openpose

./build/examples/openpose/openpose.bin \
  --video "/mnt/c/Users/<WINDOWS_USERNAME>/Downloads/test_video.mp4" \
  --model_pose BODY_25 \
  --model_folder "$HOME/openpose/models/" \
  --number_people_max 1 \
  --frame_last 100 \
  --write_json "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-project/openpose-pipeline/output/test/json" \
  --display 0 \
  --render_pose 0
```

If successful, approximately 101 JSON files should be generated.

---

# Test the WSL GPU PowerShell Wrapper

Return to normal Windows PowerShell in the repository root.

Run:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\path\to\video.mp4" `
  -FrameLast 100
```

Example:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\Users\YourName\Downloads\Side_shortened.mp4" `
  -FrameLast 100
```

This automatically:

1. resolves the Windows input path;
2. converts Windows paths to WSL paths;
3. launches `~/openpose/build/examples/openpose/openpose.bin`;
4. runs BODY_25;
5. uses the WSL CUDA build;
6. writes JSON keypoints back to Windows;
7. writes a labeled skeleton-overlay video.

Expected output:

```text
openpose-pipeline/
└── output/
    └── Side_shortened/
        ├── labeled.avi
        └── json/
            ├── ..._keypoints.json
            └── ...
```

---

# Full Video Processing

Once a 100-frame test succeeds, remove `-FrameLast`.

CPU:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video "C:\path\to\video.mp4"
```

GPU:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\path\to\video.mp4"
```

---

# Choose an Output Name

Both wrappers support:

```text
-Name
```

Example:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\path\to\video.mp4" `
  -Name "resident01_side"
```

This produces:

```text
openpose-pipeline/
└── output/
    └── resident01_side/
```

---

# JSON-Only Mode

Both wrappers support:

```text
-JsonOnly
```

CPU:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video "C:\path\to\video.mp4" `
  -JsonOnly
```

GPU:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\path\to\video.mp4" `
  -JsonOnly
```

This skips labeled-video rendering and only generates BODY_25 JSON.

---

# Custom Session Output

Both wrappers also support:

```text
-OutputDir
-LabeledVideoPath
```

These parameters are used by the resident-interface station service.

Example:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video ".\station-service\sessions\dummy_test\raw\side.mp4" `
  -OutputDir ".\station-service\sessions\dummy_test\openpose\side" `
  -LabeledVideoPath ".\station-service\sessions\dummy_test\labeled-videos\side_labeled.avi"
```

The same parameters work with:

```text
run_openpose_wsl.ps1
```

This allows CPU and GPU workstations to produce the same session directory structure.

---

# Labeled Overlay Video

Unless `-JsonOnly` is used, the wrappers create a labeled AVI containing the BODY_25 skeleton overlay.

Example:

```text
labeled.avi
```

For resident sessions:

```text
station-service/
└── sessions/
    └── <session_id>/
        └── labeled-videos/
            ├── side_labeled.avi
            └── rear_labeled.avi
```

These videos are useful for visual quality control.

---

# PowerShell Execution Policy

If PowerShell blocks a `.ps1` file:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Then rerun the desired wrapper.

This only changes the policy for the current PowerShell process.

---

# Generated Files and Git

Do not commit:

- the local `openpose/` installation;
- BODY_25 model weights;
- raw training videos;
- generated JSON keypoints;
- labeled videos;
- session analysis output.

These files should remain covered by `.gitignore`.

---

# Troubleshooting

## CPU executable not found

Check:

```powershell
Test-Path ".\openpose-pipeline\openpose\bin\OpenPoseDemo.exe"
```

If `False`, install/extract the Windows CPU OpenPose package into:

```text
openpose-pipeline/openpose/
```

---

## BODY_25 model not found

CPU:

```powershell
Test-Path ".\openpose-pipeline\openpose\models\pose\body_25\pose_iter_584000.caffemodel"
```

GPU/WSL:

```bash
ls ~/openpose/models/pose/body_25/
```

---

## WSL OpenPose executable not found

Verify:

```bash
ls ~/openpose/build/examples/openpose/openpose.bin
```

---

## NVIDIA GPU is not visible inside WSL

Inside WSL:

```bash
nvidia-smi
```

If the NVIDIA GPU is not visible, fix Windows NVIDIA driver / WSL2 GPU support before troubleshooting OpenPose.

---

## `no kernel image is available for execution on the device`

The CUDA build was not compiled for that GPU architecture.

Rebuild OpenPose/Caffe with the appropriate CUDA architecture for that NVIDIA GPU.

---

# Current Project Backends

The station-service can use either backend:

```text
OPENPOSE_BACKEND=cpu
```

or:

```text
OPENPOSE_BACKEND=wsl
```

CPU is the compatibility/development path.

WSL + CUDA is the preferred high-performance NVIDIA deployment path.

The resident does not choose the backend. It is configured once for each workstation.