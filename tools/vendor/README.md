# OpenCV YOLOX inference adapter

`opencv_yolox.py` is an unmodified copy of OpenCV Zoo's `yolox.py` (downloaded 2026-10-27):
https://github.com/opencv/opencv_zoo/blob/main/models/object_detection_yolox/yolox.py

SHA-256: `c99d8f103d93d27d0fb1807c7b91cb32d2d6c4959326cb88c801f17d00468f84`.
The upstream directory licenses these files under Apache 2.0; see the included
`OPENCV_YOLOX_LICENSE.txt` (Megvii copyright notice retained).

No pretrained weights or source racing images are included. The optional local
experiment uses OpenCV's `object_detection_yolox_2022nov.onnx`, SHA-256
`c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`.
This general-purpose COCO model is not a validated racing-boat timing model.
