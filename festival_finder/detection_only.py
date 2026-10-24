"""Locate faces with YuNet. Never loads a recognizer or reference examples."""
from pathlib import Path

import cv2
import numpy as np


class FaceLocator:
    def __init__(self, models):
        model = Path(models) / 'face_detection_yunet_2023mar.onnx'
        if not model.is_file():
            raise ValueError('The local YuNet face-detection model is missing.')
        self.detector = cv2.FaceDetectorYN.create(str(model), '', (320, 320), .8, .3, 5000)

    def locate(self, raw, directory):
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('The photo preview cannot be decoded.')
        height, width = image.shape[:2]
        scale = min(1., 1280 / max(height, width))
        frame = cv2.resize(image, (round(width*scale), round(height*scale))) if scale < 1 else image
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, rows = self.detector.detect(frame)
        boxes = []
        marked = image.copy()
        for row in rows if rows is not None else []:
            x,y,w,h = (float(v)/scale for v in row[:4])
            left,top = max(0,round(x)),max(0,round(y))
            right,bottom = min(width,round(x+w)),min(height,round(y+h))
            if right <= left or bottom <= top:
                continue
            boxes.append([left,top,right-left,bottom-top])
            cv2.rectangle(marked,(left,top),(right-1,bottom-1),(80,220,100),2)
        directory = Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        original, boxed = directory/'preview.jpg',directory/'faces.jpg'
        if not cv2.imwrite(str(original),image) or not cv2.imwrite(str(boxed),marked):
            raise ValueError('Could not save the detection previews.')
        return {'preview':str(original.resolve()),'boxed_preview':str(boxed.resolve()),'boxes':boxes}
