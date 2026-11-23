# OpenPose Runtime

This directory contains the project wrappers for OpenPose BODY_25. OpenPose binaries, model weights, and generated outputs are local and are not committed.

## Files and local directories

| Path | Purpose |
| --- | --- |
| `run_openpose_cpu.ps1` | Runs the native Windows CPU build. |
| `run_openpose_wsl.ps1` | Runs the CUDA build in WSL2. |
| `openpose/` | Local Windows CPU installation; Git-ignored. |
| `output/` | Local wrapper test output; Git-ignored. |

Both wrappers accept `-Video`, `-FrameLast`, `-Name`, `-JsonOnly`, `-OutputDir`, and `-LabeledVideoPath`. By default they write BODY_25 JSON and a labeled AVI under `output/<video-name>/`. `-JsonOnly` skips the AVI. The station-service supplies custom output paths to keep session files together.

## CPU: native Windows

1. Download the OpenPose 1.7.0 Windows CPU portable package from the [OpenPose project](https://github.com/CMU-Perceptual-Computing-Lab/openpose/releases).
2. Extract it under `openpose-pipeline/openpose/`.
3. Ensure these files exist:

```text
openpose-pipeline/openpose/bin/OpenPoseDemo.exe
openpose-pipeline/openpose/models/pose/body_25/pose_deploy.prototxt
openpose-pipeline/openpose/models/pose/body_25/pose_iter_584000.caffemodel
```

Verify the executable and model files from the repository root:

```powershell
Test-Path ".\openpose-pipeline\openpose\bin\OpenPoseDemo.exe"
Test-Path ".\openpose-pipeline\openpose\models\pose\body_25\pose_deploy.prototxt"
Test-Path ".\openpose-pipeline\openpose\models\pose\body_25\pose_iter_584000.caffemodel"
```

Run a short test:

```powershell
.\openpose-pipeline\run_openpose_cpu.ps1 `
  -Video "C:\path\to\video.mp4" `
  -FrameLast 100
```

The wrapper writes JSON frames and `labeled.avi` under `openpose-pipeline/output/<video-name>/`. `-FrameLast 100` processes frames 0 through 100; omit it to process the full video.

## NVIDIA GPU: WSL2 and CUDA

The tested GPU workflow is Windows + WSL2/Ubuntu 22.04 + the Windows NVIDIA driver + CUDA Toolkit inside WSL + OpenPose built from source. The project workstation uses an RTX 5070. This is the preferred GPU path; the native Windows CPU wrapper is the fallback.

### 1. Install WSL2

In elevated Windows PowerShell:

```powershell
wsl.exe --install -d Ubuntu-22.04
wsl --update
wsl -l -v
wsl
```

Confirm Ubuntu uses WSL2. Restart Windows if prompted.

### 2. Verify GPU access

In WSL:

```bash
nvidia-smi
```

Fix Windows NVIDIA driver/WSL GPU access before continuing if the GPU is not listed. Do not install a separate Linux display driver inside WSL.

### 3. Install CUDA Toolkit

CUDA 12.8 is the tested toolkit for the RTX 5070 setup:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-12-8

echo 'export PATH=/usr/local/cuda-12.8/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.8/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

nvcc --version
nvidia-smi
```

### 4. Install build dependencies and clone OpenPose

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake git pkg-config \
  libopencv-dev libgoogle-glog-dev libgflags-dev \
  libprotobuf-dev protobuf-compiler libboost-all-dev \
  libhdf5-dev libatlas-base-dev libleveldb-dev \
  libsnappy-dev liblmdb-dev

cd ~
git clone https://github.com/CMU-Perceptual-Computing-Lab/openpose.git
cd ~/openpose
git submodule update --init --recursive --remote
```

The wrapper expects the executable at `~/openpose/build/examples/openpose/openpose.bin` and BODY_25 models under `~/openpose/models/pose/body_25/`.

### 5. Install BODY_25 models

The model directory must contain `pose_deploy.prototxt` and `pose_iter_584000.caffemodel`. If the files are already in the Windows CPU installation, copy them into WSL (replace `<WINDOWS_USERNAME>`):

```bash
mkdir -p ~/openpose/models/pose/body_25
cp -r "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-anipose/openpose-pipeline/openpose/models/pose/body_25/"* \
  ~/openpose/models/pose/body_25/
ls -lh ~/openpose/models/pose/body_25/
```

### 6. Configure and build

For the RTX 5070, compute capability 12.0 corresponds to `sm_120`; the CUDA architecture value below is specific to that GPU. Other NVIDIA GPUs may require a different architecture.

```bash
cd ~/openpose
rm -rf build
mkdir build
cd build

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

make -j"$(nproc)"
ls ~/openpose/build/examples/openpose/openpose.bin
```

### 7. Optional direct WSL test

From WSL, set `<WINDOWS_USERNAME>` and use a short test video:

```bash
mkdir -p "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-anipose/openpose-pipeline/output/test/json"
cd ~/openpose
./build/examples/openpose/openpose.bin \
  --video "/mnt/c/Users/<WINDOWS_USERNAME>/Downloads/test_video.mp4" \
  --model_pose BODY_25 \
  --model_folder "$HOME/openpose/models/" \
  --number_people_max 1 \
  --frame_last 100 \
  --write_json "/mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-anipose/openpose-pipeline/output/test/json" \
  --display 0 \
  --render_pose 0
```

Approximately 101 JSON frames should be written.

### 8. Test the Windows WSL wrapper

From Windows PowerShell at the repository root:

```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "C:\path\to\video.mp4" `
  -FrameLast 100
```

The wrapper converts local Windows paths to WSL paths, runs the source-built executable, and writes BODY_25 JSON and a labeled AVI under `openpose-pipeline/output/<video-name>/`. Omit `-FrameLast` for a full-video run.

## Station backend selection

Set the backend in the PowerShell window that starts FastAPI:

```powershell
$env:OPENPOSE_BACKEND = "cpu"
# or
$env:OPENPOSE_BACKEND = "wsl"
```

The selection applies to the workstation, not the resident. See [the station-service guide](../station-service/README.md) for backend startup and session output paths.

## Troubleshooting

- **CPU executable/model missing:** verify the paths under `openpose/` above.
- **WSL executable missing:** check `~/openpose/build/examples/openpose/openpose.bin`.
- **GPU unavailable:** check `nvidia-smi` in WSL before building.
- **`no kernel image is available for execution on the device`:** rebuild with the CUDA architecture appropriate for that GPU; `120` is for the tested RTX 5070 only.
- **No output:** confirm the video path is local and accessible; inspect the wrapper's exit message and output directory.

Keep local OpenPose binaries, model weights, raw videos, JSON keypoints, labeled videos, and generated outputs out of Git.
