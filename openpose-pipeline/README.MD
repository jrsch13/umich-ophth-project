This is where OpenPose Pipeline code will be ran on the resident training videos

After you have pulled this repo, you will need to install Openpose locally to your machine. Do NOT commit/push openpose files as github will reject them for being to large.
1. Download OpenPose 1.7.0 Windows binaries.
2. Extract them into:

   openpose-pipeline/openpose/

3. Download BODY_25 weights into:

   openpose-pipeline/openpose/models/pose/body_25/

4. Run the pipeline scripts from openpose-pipeline/.