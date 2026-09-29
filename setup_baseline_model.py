import deeplabcut

# Creating the inital setup model using the side profile video from July 1
video = r"C:\Users\jrsch\Documents\umich-ophth-anipose\anipose-pipeline-v1\sample01\videos-raw\side_profile_test.MOV"

models_dir = r"C:\Users\jrsch\Documents\umich-ophth-anipose\models"

# Use the full_human model as the pretrained model for this initial baseline, it is part of DeepLabCut's pretrained models
deeplabcut.create_pretrained_project(
    project="ophtho-baseline-human",
    experimenter="Jason",
    videos=[video],
    model="full_human",
    working_directory=models_dir,
    copy_videos=True,
    analyzevideo=False,
    createlabeledvideo=False,
    engine=deeplabcut.Engine.TF,
)