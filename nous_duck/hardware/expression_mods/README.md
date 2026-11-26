# 表情改裝（expression_mods）

狀態：**規劃中**。上游 BOM 的「Expression package」（眼燈、投影燈、喇叭）在本機身的改裝。

| 項目 | 內容 | 狀態 |
|---|---|---|
| [眼睛：GC9A01 1.28 吋圓形螢幕](gc9a01_eyes.md) | 取代原版單色眼燈與 ADR-0006 原本規劃的 RGB LED；由 Pi 4 驅動，最外圈「狀態環」照實際鏡頭狀態顯示顏色（[ADR-0006 §4.2](../../docs/adr/ADR-0006-privacy-settings.md#42-鏡頭狀態提示眼睛螢幕2026-11-17-修訂)） | **設計 v0**：STL 量測與名目推算；螢幕未到貨、未點亮、未實機。表情與渲染程式見 [`docs/eye_expressions.md`](../../docs/eye_expressions.md)、[`robot/eyes/`](../../robot/eyes/README.md)（單元測試＋預覽圖） |
| 投影燈 | 上游 `flash_light_module`、`flash_reflector_interface` | 規劃中 |
| 喇叭 | 上游 `speaker_interface`、`speaker_stand`；音量與音訊路徑見 [ADR-0005](../../docs/adr/ADR-0005-compute-and-sensor-upgrade.md) | 規劃中 |
