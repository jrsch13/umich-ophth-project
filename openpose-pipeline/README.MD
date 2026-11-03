# This is where OpenPose Pipeline code will be ran on the resident training videos

After you have pulled this repo, you will need to install Openpose locally to your machine. Do NOT commit/push openpose files as github will reject them for being to large.
1. Download OpenPose 1.7.0 Windows binaries.
2. Extract them into:

   openpose-pipeline/openpose/

3. Download BODY_25 weights into:

   openpose-pipeline/openpose/models/pose/body_25/

4. Run the pipeline scripts from openpose-pipeline/.

# You can run OpenPosee via the .ps1 file:
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