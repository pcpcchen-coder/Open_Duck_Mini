# A 線（身體）進度

分支：`claude/duck-a-body-8fca8a`（只有本機提交）。程式：[`robot/duckd/`](../../../robot/duckd/README.md)。驗證：[duckd-2026-11-25](../../validation/duckd-2026-11-25.md)。設計：[ADR-0014](../../adr/ADR-0014-duckd-head-direct-and-single-process.md)。最後更新：2026-11-25 23:20。

| Step | 狀態 | 驗證層級 |
|---|---|---|
| A1 核心 | 完成 | 單元測試（Mac、Pi）；Mac↔Pi 真實通道端到端（模擬身體） |
| A2 安全仲裁 | 完成 | 單元測試；租約在真實通道上測過（模擬身體） |
| A3 頭部實機後端 | 程式完成，**實機沒測** | 單元測試（模擬匯流排，含「不寫腿」）；Pi 上只驗了「啟動不碰硬體」與「控制台占用時拒絕接手」 |
| A4 動作庫 | 程式完成，實機沒測 | 單元測試；真實通道（模擬身體）播過 `nod` |
| A5 presence 編排 | 程式完成，實機沒測 | 單元測試；真實通道（模擬身體） |
| A6 眼睛 | 完成（虛擬面板）；SPI 驅動卡硬體 | 單元測試；Pi 上出圖並量渲染時間（兩眼約 124 ms） |
| A7 步態 host | 載入測試完成；實機走路**等你** | Pi 上對鎖定 commit 的真上游腳本，假硬體 |
| A8 Pi 部署 | 完成 | 實機（Pi）：部署、服務啟動／停止、互斥檢查 |

怎麼執行、安全規則、還沒做的：看 duckd 的 README。測試：Mac 107 通過、3 略過。

## 需要你處理

- **實機頭部測試還沒做**：舵機控制台整晚連著匯流排。控制台按「釋放硬體」後：`sudo systemctl start duckd`、`~/duck/duckd/duckd-ctl engage`，Mac 開通道與 `python -m duckd.mock_hub --e2e`（服務預設 ±15°、30°/s）。
- 14 顆舵機整晚出力，電壓掉到 7.6 V，出現過 6.5 V 警告。
- 動作都還是 `verification: none`，要加 `--allow-unverified-gestures` 才列給 Nous。
- 要你決定：`idle` 要不要自己做小動作；頭部速度上限與視窗；`presence` 各狀態的幅度。
- 協定缺口：[`protocol/proposals/a-duckd-gaps.md`](../../../protocol/proposals/a-duckd-gaps.md)。
- Pi 上留下：`~/duck/duckd/`、`~/duck/duckd-venv/`、服務 `duckd`（disabled、已停止）。`duck-console` 沒動過。
