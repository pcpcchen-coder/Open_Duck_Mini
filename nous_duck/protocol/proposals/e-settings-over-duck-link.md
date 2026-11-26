# 提案（E 線）：Nous 經 duck-link 讀設定、收緊設定

[English](e-settings-over-duck-link.en.md)

- 來源：E 線（`robot/settings/`，[ADR-0019](../../docs/adr/ADR-0019-duck-settings-page.md)），2026-11-26
- 狀態：**提案**。schema 沒有動，兩端都沒有實作。要不要做、什麼時候做由整合線決定；要做的話先改 schema 並升版，再改兩端。

## 1. 為什麼

鴨子的設定現在只能用鴨子本機的設定網頁改（ADR-0019）。兩個情境需要 Nous 參與：

1. 使用者問 Nous「鴨子現在會不會聽聲轉頭？」「為什麼鴨子不點頭？」——Nous 要能**讀**設定，才不會亂猜。
2. 使用者說「鴨子，不要再轉頭了」「安靜一點」——Nous 要能把某一項**關掉或調小**。

不在範圍內：Nous 打開被關掉的功能、放寬任何上限、改機體量測值。這些只能由人在設定頁或本機指令做（ADR-0006 §3：身分辨識不等於授權；ADR-0019 §2.5）。

## 2. 建議的 action

### 2.1 `settings_get`（read）

- `params`：`{ "keys": ["features.track_sound", …] }`，可省略（省略＝全部）。
- `ack.data`：`{ "schema_version": 1, "revision": {"preference": 12, "measurement": 3}, "settings": { "<key>": { "value": …, "default": …, "status": "implemented" | "planned" | "hardware_missing", "effective": true | false } } }`
- `effective` 是鴨子端依各服務的回報算的（設定頁的「已生效」）。`status` 不是 `implemented` 的項目，Nous **不能**說成鴨子有這個能力（誠實規則）。
- 不回傳量測值以外的本機資訊（路徑、變更紀錄）。

### 2.2 `settings_tighten`（reversible_write）

- `params`：`{ "changes": { "<key>": <值> } }`
- 鴨子端用來源 `duck_link` 呼叫儲存層（規則已經寫在 `duck_settings.store`，有測試，但目前**沒有任何程式用這個來源呼叫**）：
  - 只接受「收緊」的方向：布林的功能開關只能 `true → false`；隱私設定只能往更嚴；有上限語意的數字（音量上限、動作幅度、角速度）只能調小。
  - 不能改機體量測值、不能寫「規劃中／硬體未到」的項目。
  - 範圍照 schema；超出就拒絕，不夾限。
- `ack`：成功回 `accepted`，`applied` 帶實際寫入的值；不是收緊方向回 `rejected`、`reason: privacy`（隱私項目）或 `invalid`（其他），`detail` 說明是哪一項。
- 回讀確認：Nous 端在 `settings_get` 看到該項 `value` 是新值且 `effective: true` 才算 `confirmed`；值對了但 `effective: false`（例如要重啟的項目）是 `unconfirmed`。

**現在的儲存層還沒做到的**：「只能收緊」目前只對隱私設定有定義（`tighten` 順序）。功能開關與數字要先在 schema 補上每一項的「收緊方向」，才能開這個 action。

### 2.3 `capabilities` 與 `hello`

- 不新增能力名稱。功能被設定關掉時，沿用現有的 `capabilities.<名稱>`：`status: unsupported`、`reason: "disabled in duck settings"`（duckd 這一版對 `tracking_sound` 已經這樣回報；`gesture` 被關掉時 `hello.gestures` 是空的，`ack` 回 `unsupported`）。
- 建議 `reason`（ack）加一個 `disabled`，和「硬體沒有」的 `unsupported` 分開：Nous 可以告訴使用者「這個功能在鴨子的設定裡被關掉了」，而不是「鴨子不會」。

### 2.4 事件

- 建議加事件 `settings_changed`：`data: { "keys": […], "source": "web" | "local_cli" | "duck_link" }`。讓 Nous 知道設定被人改了，不必輪詢。不帶值（要值就 `settings_get`）。

## 3. Nous 端的工具（搬回 AIOS 時）

| 工具 | effect | 說明 |
|---|---|---|
| `app.duck.settings_get` | `read` | 讀鴨子的設定 |
| `app.duck.settings_tighten` | `reversible_write` | 只能關掉或調小；「可逆」是指人可以在設定頁改回來，Nous 自己改不回來 |

沒有 `app.duck.settings_set`。這和 ADR-0006 §6 的 `app.duck.privacy_tighten` 是同一個形狀；兩者要不要合併，等隱私設定文件（`privacy_policy`）定案時一起決定。

## 4. 待決

1. 隱私設定以哪一邊為準（ADR-0006 說存在 Nous、同步到鴨子；ADR-0019 這一版存在鴨子）。
2. `settings_tighten` 要不要分成「這次對話有效」和「一直有效」。
3. 每一項的「收緊方向」怎麼定義數字（例如語音能量門檻：調高是收緊還是只是不同？）。
