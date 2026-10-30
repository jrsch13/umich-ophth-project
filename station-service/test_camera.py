# created this test script due to glitchy camera previews

import cv2

for camera_id in [0, 1, 2]:
    print(f"\nCamera {camera_id}")

    cap = cv2.VideoCapture(camera_id)

    if not cap.isOpened():
        print("Not available")
        cap.release()
        continue

    print("Backend:", cap.getBackendName())

    frame = None

    for i in range(5):
        ok, candidate = cap.read()
        print(f"read {i}: {ok}")

        if ok and candidate is not None:
            frame = candidate

    if frame is not None:
        filename = f"camera_{camera_id}.jpg"
        cv2.imwrite(filename, frame)
        print("Saved:", filename)

    cap.release()