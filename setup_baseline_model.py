import deeplabcut

video = r"C:\Users\jrsch\Documents\umich-ophth-anipose\anipose-pipeline-v1\sample01\videos-raw\test01.mp4"

models_dir = r"C:\Users\jrsch\Documents\umich-ophth-anipose\models"

deeplabcut.create_pretrained_project_tensorflow(
    project="ophtho-baseline-human",
    experimenter="Jason",
    videos=[video],
    model="full_human",
    working_directory=models_dir,
    copy_videos=True,
    analyzevideo=False,
    createlabeledvideo=False,
)