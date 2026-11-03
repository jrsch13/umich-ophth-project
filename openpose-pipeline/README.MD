# This is where OpenPose Pipeline code will be ran on the resident training videos

After you have pulled this repo, you will need to install Openpose locally to your machine. Do NOT commit/push openpose files as github will reject them for being to large.

1. Clone This Repository

From Windows PowerShell:
```powershell
git clone <repository-url>
cd umich-ophth-anipose
```

2. Install WSL2

Open PowerShell as Administrator:
```powershell
wsl --install -d Ubuntu-22.04
wsl --update
```

Restart Windows if requested.

Launch Ubuntu:

```powershell
wsl
```

Verify that the NVIDIA GPU is visible:

```powershell
nvidia-smi
```

You should see the installed NVIDIA GPU.

If nvidia-smi does not show the GPU, stop here and fix WSL/NVIDIA GPU support before building OpenPose.

Do not install a separate Linux NVIDIA display driver inside WSL. WSL uses the NVIDIA Windows driver.

3. Install CUDA Toolkit Inside WSL

The project has been tested using CUDA 12.8 for the WSL OpenPose build.

Inside WSL

```powershell
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-12-8
```

Add CUDA to the shell environment:

```powershell
echo 'export PATH=/usr/local/cuda-12.8/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.8/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```
Verify:
```powershell
nvcc --version
```
Also verify GPU visibility again:

```powershell
nvidia-smi
```
4. Install OpenPose Build Dependencies

Inside WSL

```powershell
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
Verify CMake:
```powershell
cmake --version
```
5. Clone OpenPose Inside WSL

Inside WSL

```powershell
cd ~
git clone https://github.com/CMU-Perceptual-Computing-Lab/openpose.git
cd openpose
git submodule update --init --recursive --remote
```

The OpenPose source should now be located at ~/openpose

6. Install BODY_25 Model Files

OpenPose requires the BODY_25 model.

The required model directory is:

~/openpose/models/pose/body_25/

At minimum, verify that this directory contains:

pose_deploy.prototxt
pose_iter_584000.caffemodel
*You may need to download these files by searching 'file name' download in google, and then clicking the first link that pops up and downloading them individually.

Create the directory if necessary:

```powershell
mkdir -p ~/openpose/models/pose/body_25
```

The .caffemodel weights are not committed to this repository because they are large files.

If an existing working OpenPose installation is available on Windows, the BODY_25 files can be copied into WSL.

For example:

```powershell
cp -r \
  /mnt/c/Users/<WINDOWS_USERNAME>/Documents/umich-ophth-anipose/openpose-pipeline/openpose/models/pose/body_25/* \
  ~/openpose/models/pose/body_25/
```
Verify:

```powershell
ls -lh ~/openpose/models/pose/body_25/
```

7. Build OpenPose for the GPU

Create a clean build directory (still in WSL):

```powershell
cd ~/openpose
rm -rf build
mkdir build
cd build
```

RTX 5070 / Blackwell Configuration

The RTX 5070 uses CUDA compute capability 12.0 (sm_120).

Configure OpenPose with this in WSL:

```powershell
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

If configuring another NVIDIA GPU, the CUDA architecture may need to be changed to match that GPU. Use ChatGPT to generate a cmake command for you

Do not blindly use 120 for every GPU.

After CMake succeeds, build OpenPose:

```powershell
make -j$(nproc)
```

Verify the resulting executable:

```powershell
ls ~/openpose/build/examples/openpose/openpose.bin
```
The expected executable is:

```powershell
~/openpose/build/examples/openpose/openpose.bin
```

8. Test OpenPose Directly in WSL

Before using the PowerShell wrapper, it is useful to confirm that OpenPose itself works.

For example:

```powershell
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

If successful, 101 JSON files should be created.

9. Recommended Usage: PowerShell Wrapper

Normal users should not need to manually run the long WSL command.

From the root of the cloned repository BACK IN REGULAR WINDOWS TERMINAL:

```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video "C:\path\to\video.mp4"
```

For example:

```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video "C:\Users\jrsch\Downloads\Side_shortened.mp4"
```

The script automatically:

resolves the Windows video path, converts it to a WSL path, launches the WSL OpenPose executable, uses BODY_25, runs GPU inference, writes JSON keypoints, writes a labeled skeleton-overlay video.

Process Only the First 101 Frames

For a quick pipeline test:

```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video "C:\Users\jrsch\Downloads\Side_shortened.mp4" `
  -FrameLast 100
```

FrameLast 100 processes frames 0 through 100. To choose another name:

```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video "C:\Users\jrsch\Downloads\Side_shortened.mp4" `
  -Name "resident01_side"
```

This produces:

openpose-pipeline/
└── output/
    └── resident01_side/

JSON-Only Mode

For automated analysis, the labeled video may not be necessary.

Run:

```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video "C:\Users\jrsch\Downloads\Side_shortened.mp4" `
  -JsonOnly
```

This disables skeleton rendering and produces only the keypoint JSON files.

This will likely be the preferred mode when OpenPose is eventually launched automatically by the resident interface.

Labeled Overlay Video

Without -JsonOnly, the script creates:

labeled.avi

This contains the original video with the BODY_25 skeleton rendered on top.

This is useful for:

visual quality control;

confirming keypoint tracking;

evaluating camera placement;

identifying occlusion problems;

debugging incorrect posture measurements.

Output

A normal run produces:

openpose-pipeline/
└── output/
    └── <video-name>/
        ├── labeled.avi
        └── json/
            ├── ..._000000000000_keypoints.json
            ├── ..._000000000001_keypoints.json
            └── ...

The output directory is ignored by Git.

Do not commit:

raw videos;

generated keypoint JSON;

labeled videos;

OpenPose binaries;

BODY_25 model weights.

PowerShell Execution Policy

If Windows blocks the .ps1 script, temporarily allow local PowerShell scripts for the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

# Run OpenPose via the .ps1 file:

I've had success running OpenPose through WSL
```powershell
.\openpose-pipeline\run_openpose_wsl.ps1 `
  -Video "path to video" `
  -Name "name of test"
  -FrameLast X
```

This version might not work but keeping it here for now:
```powershell
.\openpose-pipeline\run_openpose.ps1 `
  -Video ".\data\raw-videos\resident01_side.MOV" `
  -Name "resident01_side"
```

## You might need to run this below to allow your terminal to run local scripts:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

# To run OpenPose manually via the terminal, run:
```powershell
.\openpose-pipeline\openpose\bin\OpenPoseDemo.exe `
  --video ".\data\raw-videos\side_profile_test.MOV" `
  --model_pose BODY_25 `
  --number_people_max 1 `
  --write_json ".\openpose-pipeline\output\side_profile_test\json" `
  --write_video ".\openpose-pipeline\output\side_profile_test\labeled.avi" `
  --display 0
```

This produces:
openpose-pipeline/
└── output/
    └── side_profile_test/
        ├── labeled.avi
        └── json/
            ├── ..._000000000000_keypoints.json
            ├── ..._000000000001_keypoints.json
            └── ...