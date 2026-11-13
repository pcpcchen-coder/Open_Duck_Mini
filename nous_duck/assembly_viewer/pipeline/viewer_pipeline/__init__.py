"""Open Duck Mini v2 組裝檢視器的資料處理程式（pipeline）。

讀上游 MuJoCo 模型（`robot.xml` 與 STL），產生前端用的 `scene.json` 與 `meshes.bin`。
上游檔案一律唯讀。
"""

SCENE_SCHEMA = "nous-duck/viewer-scene@1"
