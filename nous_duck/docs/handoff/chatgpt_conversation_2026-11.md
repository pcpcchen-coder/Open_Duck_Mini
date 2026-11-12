# Open Duck資訊與組裝

來源：ChatGPT 分享連結 https://chatgpt.com/share/6af53edc-6230-83ee-968e-225375fc4c71（2026-11-12 以 `nous_duck/tools/chatgpt_share_to_md.py` 從分享頁 HTML 解出，未經人工改寫）

使用者訊息 13 則、助理回覆 63 則（含助理執行的程式碼；不含思考過程與工具回傳）。

---

## 使用者（2026-11-10 01:20 UTC）

幫我看看 OPEN DUCK 相關的資訊

---

## ChatGPT（2026-11-10 01:20 UTC）

我會先查清楚 Open Duck 有哪些版本，再對照 MicroDuck，整理實際能下載的檔案、硬體清單和 DIY 門檻。

---

## ChatGPT（2026-11-10 01:22 UTC）

目前查到，原作者公開的自製版本是 Open Duck Mini v2，CAD、列印檔、BOM 和步態策略都有。我再核對台灣的舵機價格，以及你手上的 MG995 能不能沿用。

---

## ChatGPT（2026-11-10 01:22 UTC）

**如果你想自己做一隻能走的機器鴨，我會優先選 Open Duck Mini v2。** 原作者已公開 CAD、列印檔、BOM、組裝資料和訓練好的步態模型，你可以從零件一路做到實機行走。截至 2026 年 11 月 10 日，我查到的上游主版本仍是 `v2`，尚未找到原作者發布的 `v3`。genui{"citation":{"refs":["turn1view0","turn3search2"]}}

## Open Duck Mini v2 跟 MicroDuck 差在哪？

| 項目 | Open Duck Mini v2 | Pollen Robotics MicroDuck |
|---|---|---|
| 定位 | 受迪士尼 BDX 啟發的開源 DIY 雙足機器人 | 組裝好的桌面雙足機器人 |
| 尺寸 | 腿伸直約 42 cm | 約 25 cm、800 g |
| 硬體 | Raspberry Pi Zero 2 W、14 顆 STS3215 串列舵機、2 顆 9 g 天線舵機 | RK3566、15 顆馬達、相機、ToF 深度感測、雙 IMU |
| 上手方式 | 自行列印、焊接、組裝和校正，可先用現成 ONNX 步態 | 附手把及預載動作，官方預購價 US$399，首發地區未列台灣 |

兩個專案有人員上的關聯。Open Duck Mini 作者 Antoine Pirrone 也參與了 Pollen 的 MicroDuck 開發。兩台的機構、舵機配置和控制程式各自獨立，製作時要對應各自的 BOM 和步態模型。genui{"citation":{"refs":["turn1view0","turn2view0","turn13view1","turn1view1","turn1search1"]}}

## 自己做要買什麼、花多少？

- **舵機最貴。** BOM 指定 **Feetech STS3215 7.4 V、1:345、19 kg·cm，買 14 顆**。台灣機器人王國的商品頁索引顯示 **NT$620／顆**，14 顆約 **NT$8,680**，我未能確認即時庫存。ICshop 標 **NT$1,009／顆**，頁面顯示售完並註明交期需詢問。[機器人王國](https://robotkingdom.com.tw/product/feetech-st-3215-c001-servo/) · [ICshop](https://www.icshop.com.tw/products/388400200025)。genui{"citation":{"refs":["turn2view0","turn6search0","turn13view0"]}}
- **其餘是控制板、感測器、電源和機構。** 原版用 Pi Zero 2 W、BNO055 IMU、Waveshare Bus Servo Adapter、足底開關和 2S 電源系統。列印指南指定大部分零件用 **PLA、15% 填充**，足底兩片用 **TPU、40% 填充**。作者 BOM 估 **€398.10**，加燈光、影音等表情配件為 **€432.34**。這是原作者的零件估算，台灣整機到手價我還沒核實。[原作者 BOM](https://docs.google.com/spreadsheets/d/1gq4iWWHEJVgAA_eemkTEsshXqrYlFxXAPwO515KpCJc/edit) · [列印指南](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/print_guide.md)。genui{"citation":{"refs":["turn2view0","turn2view1"]}}
- **你手上的 5 顆 MG995 可以做桌上機構原型。** 例如先試頭部擺動或自製嘴部連桿。MG995 用 PWM，原版步態控制走 Feetech 串列匯流排並讀取舵機位置，所以 MG995 無法直接代替腿部的 STS3215。genui{"citation":{"refs":["turn6search46","turn2view0","turn2view2","turn8view3"]}}

## 我會怎麼開始

1. **先跑模擬。** 用原作者公開的 ONNX 在 MuJoCo 看步態，確認自己想做的就是這個機構。[GitHub 與實機影片](https://github.com/apirrone/Open_Duck_Mini#state-of-sim2real) · [MuJoCo 訓練專案](https://github.com/apirrone/Open_Duck_Playground)。genui{"citation":{"refs":["turn1view0","turn8view1"]}}
2. **先印一組關節、買一顆舵機。** 實際檢查安裝孔、舵盤、活動範圍，再用 Runtime 驗證串列讀寫和零位。這些都過了，再買齊 14 顆。[Onshape CAD](https://cad.onshape.com/documents/64074dfcfa379b37d8a47762/w/3650ab4221e215a4f65eb7fe/e/0505c262d882183a25049d05) · [機上 Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime)。genui{"citation":{"refs":["turn1view0","turn8view0"]}}

另外有一支跟你的 **Nous／AIOS** 很搭的實機影片。Google 用兩台改裝的 Open Duck Mini v2，分別在 Pi 5 和 Jetson Orin Nano 上跑 Gemma 4 E2B，讓鴨子能看、聽和回話。你可以沿用相同的分工概念，**鴨子本體負責步態，Mac mini 上的 Nous 負責語音、視覺和行為指令**。[Google 實機展示](https://www.youtube.com/watch?v=pLwB_63yUBY)。genui{"citation":{"ref":"turn12search2"}}

---

## 使用者（2026-11-10 01:26 UTC）

我有 5 顆 MG9955 顆 MG995, 用得上嗎?

---

## ChatGPT（2026-11-10 01:26 UTC）

我先對照 v2 的關節配置和控制方式，看看這 5 顆能用在成品的哪個部位，或能先做哪種原型。

---

## ChatGPT（2026-11-10 01:26 UTC）

**用得上。如果你手上是 5 顆 MG995，我會先拿 2 顆做「會轉頭、會點頭」的桌上鴨頭。** 一顆管左右轉，一顆管上下點頭，先用你手上的 RPi 4 搭配 PCA9685 控制。舵機用獨立的 5–6 V 電源，和控制板共地。這樣可以先試 Nous 發出「看過來」「點頭」之類的指令。genui{"citation":{"ref":"turn15view1"}}

| 想做的東西 | 這 5 顆 MG995 怎麼用 |
|---|---|
| 鴨頭原型 | **2 顆**做轉頭、點頭，**第 3 顆**可試自製嘴部連桿 |
| 單腿原型 | **5 顆**剛好能做一條自製的五關節腿，固定在支架上測動作和干涉。支架與控制程式要自行改 |
| 照原版 Open Duck Mini v2 做到能走 | 腿和頭頸用原版指定的 **14 顆 STS3215**。MG995 的安裝尺寸和控制介面都不同，原版 Runtime 也需要讀取舵機位置，無法直接替換。genui{"citation":{"refs":["turn2view0","turn15view2","turn8view3","turn15view1"]}} |

如果你的第一個目標是**讓鴨子跟 Nous 互動**，先用現有的 MG995 做鴨頭就能開工。如果目標是**讓鴨子走起來**，我會先買 **1 顆 STS3215** 配原版列印件試裝和校正，通過後再買齊。

---

## 使用者（2026-11-10 01:29 UTC）

STS3215 要 7v or 12v ?

---

## ChatGPT（2026-11-10 01:29 UTC）

我核對一下 Open Duck Mini v2 的 BOM 和舵機型號，避免下單買到不同電壓的版本。

---

## ChatGPT（2026-11-10 01:29 UTC）

照 **Open Duck Mini v2 原版**做，買 **7.4 V**。如果賣場只寫「7V」，請確認完整型號是 **Feetech STS3215-C001，7.4 V、齒輪比 1:345、約 19.5 kg·cm**。原作者的 BOM 指定這個 7.4 V 版本，共 **14 顆**。genui{"citation":{"refs":["turn16view0","turn16search12","turn8view3"]}}

**12 V 的 C018 是另一個版本。** 原版用 **2S 鋰電池**，標稱 7.4 V、充滿 8.4 V，所以採購時直接認 **C001** 最穩。genui{"citation":{"refs":["turn16search12","turn2view0","turn8view3"]}}

---

## 使用者（2026-11-10 01:34 UTC）

Open Duck Mini v2 我要開始列印! 檔案在哪?

---

## ChatGPT（2026-11-10 01:34 UTC）

我會核對原作者的 STL 資料夾和列印清單，找出能直接下載的連結。

---

## 使用者（2026-11-10 01:34 UTC）

完成後 多高啊?

---

## ChatGPT（2026-11-10 01:34 UTC）

**Open Duck Mini v2 組好後，雙腿伸直時約 42 公分高。** 平常站姿如果屈膝會更低，原作者只標了伸直時的高度。genui{"citation":{"ref":"turn20view0"}}

**列印檔在這裡。** [下載原作者 v2 ZIP](https://github.com/apirrone/Open_Duck_Mini/archive/refs/heads/v2.zip)，解壓後進 `Open_Duck_Mini-2/print/` 找 `.stl`。也可以直接開 [GitHub 的 STL 資料夾](https://github.com/apirrone/Open_Duck_Mini/tree/v2/print) 或 [原作者列印清單](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/print_guide.md)。照清單是 **36 種 STL、共 51 件**，其中 **49 件 PLA（15% 填充）、2 件 TPU（40% 填充）**。genui{"citation":{"refs":["turn17view0","turn18view0"]}}

**第一盤可以先印一隻腳。** `foot_top.stl`、`foot_side.stl`、`foot_bottom_pla.stl` 各一件，柔軟腳底 `foot_bottom_tpu.stl` 另外用 TPU 印一件。等 **STS3215-C001** 到貨，先試裝確認舵機和螺絲孔的配合，再印第二隻腳。genui{"citation":{"refs":["turn17view0","turn19view0"]}}

---

## 使用者（2026-11-10 01:37 UTC）

是不是有大之一點的?

---

## ChatGPT（2026-11-10 01:37 UTC）

我會找比 42 公分的 Mini v2 更大的 BDX 風格機器鴨，看看哪些有公開列印檔，哪些已經有實機走路。

---

## ChatGPT（2026-11-10 01:38 UTC）

**有。比 42 公分的 Open Duck Mini v2 更大、也有實機走路展示的，我找到 Kayden Knapik 的 BDX-R，約 65–70 公分高。** 這個高度是第三方估計，作者公開了 STEP 檔和實機步行影片。[BDX-R CAD](https://github.com/BDX-R/BDX-R-CAD) · [作者的實機展示](https://kaydenknapik.com/project1.html)。genui{"citation":{"refs":["turn33view3","turn32view2","turn34view0","turn25view0"]}}

但做大版的成本跳很多。**BDX-R 用 Robstride 無刷致動器，16 顆馬達約 US$2,800**，髖部承力件也改成 CNC 鋁件。你前面看的 **STS3215-C001** 則是 Mini v2 的用料。genui{"citation":{"refs":["turn30view4","turn16view0"]}}

如果你想要的是**只大一點，約 50–55 公分，還能照檔案列印、用 STS3215 走路**，我目前還沒找到有公開列印檔和實機步行驗證的版本。切片設成 120% 雖然會把外形放大到約 50 公分，舵機座和螺絲孔也會一起放大，得回 CAD 重做配合。**如果你這次想先印出一隻能走的鴨子，我會先印原尺寸 v2。** genui{"citation":{"refs":["turn33view3","turn17view0","turn19view0"]}}

---

## 使用者（2026-11-10 01:44 UTC）

先來做原版的吧!

---

## ChatGPT（2026-11-10 01:44 UTC）

好，先做原尺寸 Open Duck Mini v2。我會準備第一隻腳的列印檔和用料，讓你可以先試印、試裝。

---

## ChatGPT（2026-11-10 01:44 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-10 01:45 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-10 01:45 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-10 01:45 UTC）

The output of this plugin was redacted.

---

## 使用者（2026-11-10 01:45 UTC）

幫我列張表，比較跟 microduck 的差異與優劣

---

## ChatGPT（2026-11-10 01:45 UTC）

第一隻腳的 4 個 STL 已逐一對照原作者檔案。比較表會把自製成本和成品預購價分開，也會標出台灣的供貨狀況。

---

## ChatGPT（2026-11-10 01:45 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-10 01:46 UTC）

**你這次想從列印、組裝一路做到雙足行走，選 Open Duck Mini v2 比較合適。** 如果目標是拿到一台小型機器鴨，直接接 Nous 做視覺、語音和行為控制，Pollen 的 MicroDuck 有更多內建感測器和控制介面。genui{"citation":{"refs":["turn1view0","turn38view0","turn38view2"]}}

| 比較項目 | Open Duck Mini v2 原版 | Pollen Robotics MicroDuck |
|---|---|---|
| **尺寸** | 腿伸直約 **42 cm**，機構較大，適合拆裝和改造。genui{"citation":{"ref":"turn20view0"}} | 約 **25 cm、780 g**，比較適合放桌上或帶出門。genui{"citation":{"ref":"turn38view0"}} |
| **硬體與維修** | Pi Zero 2 W、**14 顆 STS3215-C001**、2 顆 9 g 天線舵機。CAD、STL、BOM 都公開，列印件可以自行補印。genui{"citation":{"refs":["turn1view0","turn2view0","turn17view0"]}} | RK3566、**15 顆馬達**，官方有備用馬達套件。控制與訓練軟體公開，原廠整機製造資料未完整公開。genui{"citation":{"refs":["turn37view1","turn38view1","turn38view2"]}} |
| **製作難度** | 原版清單有 **51 件列印件**，要自行接線、裝配和校正。你能掌握整台的結構，代價是首次走起來需要更多工。genui{"citation":{"refs":["turn18view0","turn19view0","turn8view0"]}} | 成品附電池和手把，收到後可直接操作預載動作。genui{"citation":{"refs":["turn37view1","turn38view0"]}} |
| **動作與訓練** | 有實機步行展示和可下載的 **ONNX 步態**，也能用 MuJoCo Playground 自己訓練。genui{"citation":{"refs":["turn1view0","turn8view1"]}} | 預載走路、坐下、起身、用嘴夾物等動作，也公開模擬、訓練和部署流程。genui{"citation":{"refs":["turn37view1","turn38view2"]}} |
| **感測與 Nous 整合** | 原版有 **BNO055 IMU 和足底開關**。相機、麥克風、喇叭屬於加裝項目，適合自己決定介面和配置。genui{"citation":{"ref":"turn2view0"}} | 內建 **相機、ToF 深度感測、雙 IMU、麥克風、喇叭及 NFC**，已有 `robotctl`、JSON-RPC 和 WebRTC 影像串流，做互動的起點較完整。genui{"citation":{"refs":["turn38view0","turn38view2"]}} |
| **價格與台灣取得** | 作者 BOM 估 **€398.10**，加表情配件約 **€432.34**。這是零件估算，台灣實際採購總價尚未核實。genui{"citation":{"ref":"turn2view0"}} | 官方成品預購 **US$399**，另計稅與運費。截至 **2026/11/10**，官方首發地區仍未列台灣。genui{"citation":{"ref":"turn38view0"}} |

**今天先印一隻腳。** 我把原作者的 4 個 STL 和繁中試印說明整理好了，STL 已逐一比對原檔。切片用 **100% 原尺寸**，先印 3 件 **PLA（15% 填充）**，柔軟腳底再用 **TPU（40% 填充）**印 1 件。拿 **1 顆 STS3215-C001** 試裝，確認舵機能貼合、螺絲孔對得上、關節轉動無干涉，再開始印第二隻腳。genui{"citation":{"refs":["turn17view0","turn36view0"]}}

[Open_Duck_Mini_v2_First_Foot.zip](sandbox:/mnt/data/Open_Duck_Mini_v2_First_Foot.zip)

---

## 使用者（2026-11-11 06:39 UTC）

腳印完要印啥？

---

## ChatGPT（2026-11-11 06:42 UTC）

我對一下原版組裝圖，確認腳印完後，下一盤的小腿零件要印哪些、各幾件。

---

## ChatGPT（2026-11-11 06:42 UTC）

如果你只印了試印包的**一隻腳**，先把第二隻也印出來，左右腳用同一組 STL。兩隻腳都印完，就接著印**小腿**。genui{"citation":{"ref":"turn39view0"}}

| STL | 下一盤：兩條小腿 | 整台用量（含大腿） |
|---|---:|---:|
| `knee_to_ankle_left_sheet.stl` | 2 件 | 4 件 |
| `knee_to_ankle_right_sheet.stl` | 2 件 | 4 件 |
| `leg_spacer.stl` | 2 件 | 4 件 |

這一盤共 **6 件，PLA、15% 填充、100% 原尺寸**。每條小腿各用一片 `left_sheet`、一片 `right_sheet` 和一個 `leg_spacer`。大腿也用這三個檔案，所以小腿試裝順利後，同一盤再印一次就能備齊兩條大腿。genui{"citation":{"refs":["turn39view0","turn39view1"]}}

試裝時，**先把腳部舵機線穿過 `right_sheet`，再鎖上側板**。[原版 STL 資料夾](https://github.com/apirrone/Open_Duck_Mini/tree/v2/print) · [小腿組裝圖](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-shins)。genui{"citation":{"ref":"turn39view0"}}

---

## 使用者（2026-11-11 06:47 UTC）

再來下一步 要印啥？ 我想要排滿一起印

---

## ChatGPT（2026-11-11 06:47 UTC）

我先按雙腳和兩條小腿都已印完來排，核對大腿、髖部和軀幹的件數，再量 STL 的占板尺寸。

---

## ChatGPT（2026-11-11 06:47 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'set -euo pipefail
plate_dir=$(mktemp -d /tmp/openduck-plate.XXXXXX)
echo "$plate_dir"
plate_src=https://raw.githubusercontent.com/apirrone/Open_Duck_Mini/b23317a485b3cec7d8417f352478778b3475173c/print
pids=()
for name in knee_to_ankle_left_sheet knee_to_ankle_right_sheet leg_spacer left_roll_to_pitch right_roll_to_pitch roll_motor_bottom roll_motor_top trunk_bottom trunk_top; do
  curl -fsSL --max-time 15 "$plate_src/$name.stl" -o "$plate_dir/$name.stl" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do wait "$pid"; done
python - "$plate_dir" <<'"'PY'
from pathlib import Path
from struct import iter_unpack
import sys
for f in sorted(Path(sys.argv[1]).glob('*.stl')):
    b=f.read_bytes()
    triangles=list(iter_unpack('<12fH', b[84:]))
    coords=[(tri[i],tri[i+1],tri[i+2]) for tri in triangles for i in (3,6,9)]
    print(f.stem, [round(max(axis)-min(axis), 2) for axis in zip(*coords)])
PY"
````

---

## ChatGPT（2026-11-11 06:48 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "python - <<'PY'
import itertools
import math
import random
dimensions = {
    \"left sheet\": (31, 71, 2), \"right sheet\": (31, 71, 2), \"spacer\": (29, 37, 2),
    \"left roll\": (47, 87, 1), \"right roll\": (47, 87, 1), \"roll bottom\": (32, 32, 2),
    \"roll top\": (29, 38, 2), \"trunk bottom\": (74, 108, 1), \"trunk top\": (101, 126, 1),
}
parts = [(name, w, h) for name, (w, h, n) in dimensions.items() for _ in range(n)]
def pack(parts, bed, gap=8, edge=8):
    free = [(edge, edge, bed - 2*edge + gap, bed - 2*edge + gap)]
    placed = []
    for name, a, b in parts:
        options = [(min(w-i,h-j),max(w-i,h-j),x,y,i,j)
                   for x,y,w,h in free for i,j in [(a+gap,b+gap),(b+gap,a+gap)]
                   if i<=w and j<=h]
        if not options:
            return
        _,_,px,py,pw,ph=min(options)
        placed.append((name,px,py,pw-gap,ph-gap))
        more=[]
        for x,y,w,h in free:
            if px>=x+w or px+pw<=x or py>=y+h or py+ph<=y:
                more.append((x,y,w,h))
                continue
            if px>x: more.append((x,y,px-x,h))
            if py>y: more.append((x,y,w,py-y))
            if px+pw<x+w: more.append((px+pw,y,x+w-px-pw,h))
            if py+ph<y+h: more.append((x,py+ph,w,y+h-py-ph))
        free=[r for r in set(more) if not any(r"'!=q and r[0]>=q[0] and r[1]>=q[1] and r[0]+r[2]<=q[0]+q[2] and r[1]+r[3]<=q[1]+q[3] for q in more)]
    for p,q in itertools.combinations(placed,2):
        _,x,y,w,h=p
        _,i,j,a,b=q
        assert x+w+gap<=i or i+a+gap<=x or y+h+gap<=j or j+b+gap<=y
    assert all(edge<=x and edge<=y and x+w<=bed-edge and y+h<=bed-edge for _,x,y,w,h in placed)
    return placed
rng=random.Random(42)
for bed in [220, 250, 256, 300]:
    for p in [parts, [p for p in parts if not p[0].startswith('"'trunk')]]:
        found=pack(sorted(p,key=lambda p:p[1]*p[2],reverse=True),bed)
        for _ in range(1000):
            if found:
                break
            found=pack(sorted(p,key=lambda p:p[1]*p[2]*rng.uniform(.55,1.35),reverse=True),bed)
        print(bed,len(p),bool(found))
        if found and bed==256 and len(p)==14:
            print(*found,sep='\\n')
PY"
````

---

## ChatGPT（2026-11-11 06:48 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "python - <<'PY'
import itertools, random
groups=[('L',31,71,2),('R',31,71,2),('S',29,37,2),('HL',47,87,1),('HR',47,87,1),('B',32,32,2),('T',29,38,2),('TB',74,108,1),('TT',101,126,1)]
parts=[(f'{n}{k+1}' if count>1 else n,w,h) for n,w,h,count in groups for k in range(count)]
def place(parts,bed,gap,edge):
    free=[(edge,edge,bed-edge+gap,bed-edge+gap)]
    placements=[]
    for name,w,h in parts:
        options=[(min(x2-x-i,y2-y-j),max(x2-x-i,y2-y-j),x,y,i,j) for x,y,x2,y2 in free for i,j in ((w+gap,h+gap),(h+gap,w+gap)) if i<=x2-x and j<=y2-y]
        if not options:
            return None
        _,_,px,py,pw,ph=min(options)
        placements.append((name,px,py,pw-gap,ph-gap))
        new=[]
        for x,y,x2,y2 in free:
            if x>=px+pw or x2<=px or y>=py+ph or y2<=py:
                new.append((x,y,x2,y2))
            else:
                if x<px:new.append((x,y,px,y2))
                if x2>px+pw:new.append((px+pw,y,x2,y2))
                if y<py:new.append((x,y,x2,py))
                if y2>py+ph:new.append((x,py+ph,x2,y2))
        free=[a for a in set(new) if not any(a"'!=b and b[0]<=a[0] and b[1]<=a[1] and b[2]>=a[2] and b[3]>=a[3] for b in new)]
    for (_,x,y,w,h),(_,i,j,a,b) in itertools.combinations(placements,2):
        assert x+w+gap<=i or i+a+gap<=x or y+h+gap<=j or j+b+gap<=y
    return placements
rng=random.Random(2026)
for bed,gap,edge,exclude in [(256,6,6,()),(256,5,5,()),(256,8,8,('"'TT',)),(256,8,8,('TB',)),(220,6,6,('TT',)),(220,5,5,('TT',)),(300,8,8,())]:
    options=[p for p in parts if p[0] not in exclude]
    for i in range(4500):
        found=place(sorted(options,key=lambda p:p[1]*p[2]*rng.uniform(.30,1.7),reverse=True),bed,gap,edge)
        if found:
            break
    print(bed,gap,edge,exclude,bool(found), 'used', (max(x+w for _,x,y,w,h in found),max(y+h for _,x,y,w,h in found)) if found else None)
    if found and not exclude and bed==256:
        print(found)
PY"
````

---

## ChatGPT（2026-11-11 06:48 UTC）

如果**雙腳和兩條小腿都印完了**，下一盤就排 **兩條大腿＋左右髖部＋軀幹，共 14 件**。大腿沿用小腿的三個 STL，各再印 2 件。整盤都用 **PLA、15% 填充、100% 原尺寸**。genui{"citation":{"refs":["turn40view0","turn40view1"]}}

| 部位 | STL | 這次印 |
|---|---|---:|
| 大腿 | `knee_to_ankle_left_sheet.stl` | 2 |
| 大腿 | `knee_to_ankle_right_sheet.stl` | 2 |
| 大腿 | `leg_spacer.stl` | 2 |
| 髖部 | `left_roll_to_pitch.stl` | 1 |
| 髖部 | `right_roll_to_pitch.stl` | 1 |
| 髖部 | `roll_motor_bottom.stl` | 2 |
| 髖部 | `roll_motor_top.stl` | 2 |
| 軀幹 | `trunk_bottom.stl` | 1 |
| 軀幹 | `trunk_top.stl` | 1 |

- **256 × 256 mm 平台**：我用原版 STL 外框估排，**14 件可放同一盤**。先擺最大的 `trunk_top`、`trunk_bottom`，再用側板和小件填空。開印前看切片預覽，確認支撐和裙邊也在可印區內。
- **220 × 220 mm 平台**：先排**大腿＋髖部共 12 件**。還有空間就試放 `trunk_bottom`，把最大的 `trunk_top` 留下一盤。

[原版 STL 資料夾](https://github.com/apirrone/Open_Duck_Mini/tree/v2/print) · [大腿與髖部組裝圖](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-thighs)

---

## 使用者（2026-11-12 00:30 UTC）

好！都印完了，再來印哪些？

---

## ChatGPT（2026-11-12 00:33 UTC）

我先按上一批的大腿、髖部和軀幹都印好了來算，核對還剩哪些 STL，看看下一盤可以一起放哪些。

---

## ChatGPT（2026-11-12 00:33 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'set -euo pipefail
plate_dir=$(mktemp -d /tmp/openduck-final-plate.XXXXXX)
echo "$plate_dir"
plate_src=https://raw.githubusercontent.com/apirrone/Open_Duck_Mini/b23317a485b3cec7d8417f352478778b3475173c/print
pids=()
for name in neck_left_sheet neck_right_sheet head_pitch_to_yaw head_yaw_to_roll head_roll_mount head head_bot_sheet left_antenna_holder right_antenna_holder left_cache right_cache body_front body_middle_bottom body_middle_top body_back battery_pack_lid; do
  curl -fsSL --max-time 12 "$plate_src/$name.stl" -o "$plate_dir/$name.stl" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do wait "$pid"; done
python - "$plate_dir" <<'"'PY'
from pathlib import Path
from struct import iter_unpack
import sys
for f in sorted(Path(sys.argv[1]).glob('*.stl')):
    b=f.read_bytes()
    coords=[(tri[i],tri[i+1],tri[i+2]) for tri in iter_unpack('<12fH', b[84:]) for i in (3,6,9)]
    print(f.stem, [round(max(axis)-min(axis), 2) for axis in zip(*coords)])
PY"
````

---

## 使用者（2026-11-12 00:34 UTC）

好！都印完了，再來印哪些？

---

## ChatGPT（2026-11-12 00:35 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "python - <<'PY'
import random
parts = [
    ('body_middle_top',150,110), ('head_yaw_to_roll',88,80),
    ('head_pitch_to_yaw',72,45), ('head_roll_mount',65,40),
    ('neck_left_sheet',58,31), ('neck_right_sheet',58,31),
    ('left_antenna_holder',42,27), ('right_antenna_holder',42,27),
]
def pack(bed, ordered):
    gap, edge = 6, 6
    free = [(edge,edge,bed-edge+gap,bed-edge+gap)]
    result=[]
    for n,a,b in ordered:
        fit=[(min(x2-x-w,y2-y-h),max(x2-x-w,y2-y-h),x,y,w,h)
             for x,y,x2,y2 in free
             for w,h in [(a+gap,b+gap),(b+gap,a+gap)] if x+w<=x2 and y+h<=y2]
        if not fit: return
        _,_,p,q,w,h=min(fit)
        result.append((n,p,q,w-gap,h-gap))
        new=[]
        for x,y,x2,y2 in free:
            if x>=p+w or x2<=p or y>=q+h or y2<=q:
                new.append((x,y,x2,y2))
                continue
            if x<p:new.append((x,y,p,y2))
            if y<q:new.append((x,y,x2,q))
            if p+w<x2:new.append((p+w,y,x2,y2))
            if q+h<y2:new.append((x,q+h,x2,y2))
        free=[a for a in set(new) if not any(a"'!=b and b[0]<=a[0] and b[1]<=a[1] and b[2]>=a[2] and b[3]>=a[3] for b in new)]
    return result
rng=random.Random(10)
for bed in (220,256):
    for count in (8,6):
        for k in range(3000):
            p=pack(bed,sorted(parts[:count],key=lambda row:row[1]*row[2]*rng.uniform(.3,1.5),reverse=True))
            if p:break
        print(bed,count,p)
PY'
````

---

## ChatGPT（2026-11-12 00:35 UTC）

**下一盤印頸部、頭部關節、天線座和機身上蓋，共 8 件。** 我用原版 STL 的外框估排，**220 × 220 mm 和 256 × 256 mm** 都放得下。全部用 **PLA、15% 填充、100% 原尺寸**，各印 1 件。開印前看一下支撐和裙邊有沒有重疊。genui{"citation":{"ref":"turn69view0"}}

| 部位 | 這一盤要放的 STL |
|---|---|
| 頸部側板 | `neck_left_sheet.stl`、`neck_right_sheet.stl` |
| 頭部關節 | `head_pitch_to_yaw.stl`、`head_yaw_to_roll.stl`、`head_roll_mount.stl` |
| 天線座 | `left_antenna_holder.stl`、`right_antenna_holder.stl` |
| 機身上蓋 | `body_middle_top.stl` |

**後面還有 15 件。** 頭殼 `head.stl` 約 **200 × 197 mm**，頭底板 `head_bot_sheet.stl` 約 **194 × 192 mm**，建議各自當一盤的主件，有空位再塞小件。genui{"citation":{"ref":"turn69view0"}}

- **外殼與電池艙 6 件**：`left_cache`、`right_cache`、`body_front`、`body_middle_bottom`、`body_back`、`battery_pack_lid`。
- **眼睛、燈光和喇叭 7 件**：`left_eye`、`right_eye`、`bulb`、`flash_light_module`、`flash_reflector_interface`、`speaker_interface`、`speaker_stand`。genui{"citation":{"ref":"turn69view0"}}

組裝時，**鎖定頭部關節前，先把 `head_bot_sheet` 和 `body_middle_top` 套進去**，就能省一次拆頭重裝。[原版 STL 資料夾](https://github.com/apirrone/Open_Duck_Mini/tree/v2/print) · [頭部組裝圖](https://github.com/apirrone/Open_Duck_Mini/blob/v2/docs/assembly_guide.md#assemble-the-head-mechanism)。genui{"citation":{"ref":"turn69view1"}}

---

## 使用者（2026-11-12 00:50 UTC）

你幫我把整隻鴨子的 3D 模型畫給我 in html, 並且給我ＢＯＭ爆炸功能檢視每個元件，我在組裝的時候要用！也要包含所有電子元件跟馬達！並在網頁中給我逐步的組裝順序指引！

---

## ChatGPT（2026-11-12 00:50 UTC）

我會做成可離線開啟的 HTML 組裝檢視器，用 Open Duck Mini v2 原版模型定位零件，並把爆炸視圖、BOM 和組裝步驟連動起來。

---

## ChatGPT（2026-11-12 00:50 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'set -euo pipefail
mkdir -p /tmp/duck-viewer /mnt/data
cd /tmp/duck-viewer
curl -fL --silent --show-error --max-time 95 -o upstream.zip https://codeload.github.com/apirrone/Open_Duck_Mini/zip/b23317a485b3cec7d8417f352478778b3475173c
unzip -q -o upstream.zip
du -sh .
find . -maxdepth 3 -type d | head -60'
````

---

## ChatGPT（2026-11-12 00:50 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'set -u
cd /tmp/duck-viewer
ls -lh
p=https://raw.githubusercontent.com/apirrone/Open_Duck_Mini/b23317a485b3cec7d8417f352478778b3475173c
mkdir -p inspect
for name in robot.xml robot_motors.xml scene.xml robot_no_visual.xml; do
 curl -fLsS --max-time 18 "$p/mini_bdx/robots/open_duck_mini_v2/$name" -o "inspect/$name" &
done
curl -fLsS --max-time 18 "$p/docs/assembly_guide.md" -o inspect/assembly.md &
curl -fLsS --max-time 18 "$p/docs/print_guide.md" -o inspect/print.md &
curl -fLsS --max-time 18 https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js -o inspect/three.min.js &
wait
ls -lh inspect
command -v chromium || command -v google-chrome || true
node -v
python - <<'"'PY'
import importlib.util
for p in ['numpy','trimesh','mujoco','scipy','playwright','PIL']:
 print(p, bool(importlib.util.find_spec(p)))
PY
ls -d /usr/share/fonts/* /opt/*"
````

---

## ChatGPT（2026-11-12 00:50 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'cd /tmp/duck-viewer
repo=(Open_Duck_Mini-*)
find "$repo/mini_bdx/robots/open_duck_mini_v2" -maxdepth 2 -type f | head -140
printf '"'\\n--- docs ---\\n'
find \""'$repo/docs" -maxdepth 2 -type f | sort
printf '"'\\n--- tools ---\\n'
ls -lh inspect
command -v chromium || command -v google-chrome
printenv CODEX_PRIMARY_RUNTIME_NODE_MODULES
python - <<'PY'
import importlib.util
for p in ['numpy','trimesh','mujoco','scipy','playwright','PIL']:
 print(p, bool(importlib.util.find_spec(p)))
PY"
````

---

## ChatGPT（2026-11-12 00:51 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'cd /tmp/duck-viewer
R=(Open_Duck_Mini-*)
D="$R/mini_bdx/robots/open_duck_mini_v2"
sed -n '"'1,110p' \""'$D/robot_motors.xml"
cat "$D/scene.xml"
cat "$R/docs/configure_motors.md"
sed -n '"'1,175p' \""'$R/docs/assembly_guide.md"
python - "$D" <<'"'PY'
import sys,xml.etree.ElementTree as E
from collections import Counter
from pathlib import Path
p=Path(sys.argv[1])
for x in ('robot.xml','robot_motors.xml'):
 root=E.parse(p/x)
 print(x, Counter(g.get('mesh') for g in root.findall('./worldbody//geom') if g.get('mesh')))
 for b in root.findall('./worldbody//body'):
  j=b.find('joint')
  print(b.get('name'),b.get('pos'),b.get('quat'),j.get('name') if j is not None else '',[g.get('mesh') for g in b.findall('geom') if g.get('mesh')])
PY"
````

---

## ChatGPT（2026-11-12 00:51 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'cd /tmp/duck-viewer
R=(Open_Duck_Mini-*)
D="$R/mini_bdx/robots/open_duck_mini_v2"
rg -n -C 2 '"'mesh=\"board\"|mesh=\"head\"|mesh=\"sg90\"|mesh=\"bno055\"|mesh=\"cell\"|mesh=\"holder\"' \""'$D/robot.xml"
cat "$D/config.json"
du -sh "$D" "$R/print"
sed -n '"'220,300p' \""'$R/docs/assembly_guide.md"
find "$R/print" -maxdepth 1 -type f | sed '"'s|.*/||' | sort
head -25 inspect/three.min.js | cut -c1-150"
````

---

## ChatGPT（2026-11-12 00:51 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > photos.py <<'PY'
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
from io import BytesIO
from PIL import Image

ids={
'servo-zero':'e3c4aefa-5e0a-4d4e-89f4-82df9bf30e29',
'trunk-bearings':'9ed8591a-7c96-4410-8d7e-9b7d88c6bd1f','trunk-screws':'ae36b396-a34a-4691-8e62-fd916cd1f76c',
'foot-bottom':'6749a5ba-cea9-4b0a-ac32-f32e130fd057','foot-fit':'197cd9b7-05a6-46ed-9af5-d2def37970c8','foot-switch':'71b9ad91-864e-423f-97a3-911d65182ab9',
'shin-inserts':'41eb01a2-d6f9-43b1-a83e-d14785907425','shin-wire':'a1432505-6b6c-4765-aea6-0a7a0b8b220b',
'thigh-zero':'951157a4-26dc-41bb-b97f-18dbbb0c1cd3','hip-bracket':'768f1664-030c-4432-9071-c52d79d3ef6b','hip-mount':'a7169791-9f0a-4827-aea7-00ab1d0f6212',
'neck':'f96fe44f-a7bc-423e-a925-4aef3e7bf568','head-roll':'4648cd6c-391e-41e4-9617-4ecebfa9215b',
'imu':'8772996d-5906-48fa-8cbe-6b6823982375',
'battery':'371db809-7cb3-47e1-b277-7fc2bdf21025','head-internal':'91284081-a563-4c02-bb3d-194b3afbc25c',
'body':'679a9cd2-89ca-41e8-9d03-f93fc040068b','assembled':'312ec747-8eb4-4145-92eb-c1c3ddba80da',
'feet-wiring':'d3376494-4690-4484-8352-132e6284731a',
}
Path('photos').mkdir(exist_ok=True)
def get(pair):
 name,id=pair
 try:
  with urlopen('https://github.com/user-attachments/assets/'+id,timeout=22) as response:
   pic=Image.open(BytesIO(response.read())).convert('RGB')
  pic.thumbnail((960,800))
  pic.save(f'photos/{name}.jpg', quality=84, optimize=True)
  return name, pic.size
 except Exception as e: return name, str(e)
with ThreadPoolExecutor(max_workers=8) as pool:
 for result in pool.map(get,ids.items()): print(result,flush=True)
PY
python photos.py"
````

---

## ChatGPT（2026-11-12 00:52 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > model.py <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
from scipy.spatial.transform import Rotation
import numpy as np
from collections import defaultdict
from functools import lru_cache
from scipy.optimize import linear_sum_assignment

root=next(Path('.').glob('Open_Duck_Mini-*'))
cad=root/'mini_bdx/robots/open_duck_mini_v2'
printed=root/'print'
mesh_dtype=np.dtype([('normal','<f4',(3,)),('verts','<f4',(3,3)),('flag','<u2')])
@lru_cache(maxsize=None)
def mesh(path):
 data=path.read_bytes()
 return np.frombuffer(data,dtype=mesh_dtype,offset=84).copy()
@lru_cache(maxsize=None)
def bounds(path):
 pts=mesh(path)['verts'].reshape(-1,3)
 return pts.min(axis=0),pts.max(axis=0)
def offset(node):
 return np.fromstring(node.get('pos','0 0 0'),sep=' ')
def rotation(node):
 q=np.fromstring(node.get('quat','1 0 0 0'),sep=' ')
 return Rotation.from_quat(q[[1,2,3,0]])
base_rot=Rotation.from_matrix([[0,1,0],[0,0,1],[1,0,0]])
geoms=[]
joints={}
bodies={}
def walk(node,p,r):
 loc=p+r.apply(offset(node))
 rot=r*rotation(node)
 name=node.get('name')
 bodies[name]=(loc,rot)
 joint=node.find('joint')
 if joint is not None:
  joints[joint.get('name')]=loc+rot.apply(offset(joint))
 for geom in node.findall('geom'):
  asset=geom.get('mesh')
  if not asset:continue
  gpos=loc+rot.apply(offset(geom))
  grot=rot*rotation(geom)
  path=cad/(asset+'.stl')
  low,high=bounds(path)
  center=gpos+grot.apply((low+high)/2)
  geoms.append(dict(asset=asset,p=gpos,r=grot,body=name,center=center,rgba=geom.get('rgba','')))
 for child in node.findall('body'):walk(child,loc,rot)
walk(ET.parse(cad/'robot.xml').find('./worldbody/body'),np.zeros(3),base_rot)
motors=defaultdict(list)
for g in geoms:
 if g['asset'].startswith('wj-') or g['asset'].endswith('palonier'):
  motors[tuple(np.round(g['p'],5))].append(g)
motor_ids={'left_hip_yaw':20,'left_hip_roll':21,'left_hip_pitch':22,'left_knee':23,'left_ankle':24,
'right_hip_yaw':10,'right_hip_roll':11,'right_hip_pitch':12,'right_knee':13,'right_ankle':14,
'neck_pitch':30,'head_pitch':31,'head_yaw':32,'head_roll':33}
mset=list(motors.values())
assignable=list(motor_ids)
points=np.array([next(x['center'] for x in g if x['asset']=='drive_palonier') for g in mset])
targets=np.array([joints[j] for j in assignable])
dist=np.linalg.norm(points[:,None]-targets[None,:],axis=2)
ridx,cidx=linear_sum_assignment(dist)
assignments={assignable[c]:mset[r] for r,c in zip(ridx,cidx)}
if __name__=='__main__':
 print('grouped motors',len(mset), [len(m) for m in mset])
 for r,c in zip(ridx,cidx):
  print(motor_ids[assignable[c]],assignable[c],mset[r][0]['body'],round(dist[r,c]*1000,2),np.round(points[r]*1000))
 print('positions')
 for g in geoms:
  name=g['asset']
  if name.startswith('wj-') or name.endswith('palonier'): continue
  if name not in {'foot_bottom_tpu','board','head','head_bot_sheet','body_front','body_back','body_middle_top','cell','holder','bms','usb_c_charger','power_switch','raspberrypizerow','sg90','antenna','bno055','left_cache','right_cache'}: continue
  print(name,g['body'],np.round(g['p']*1000),np.round(g['center']*1000),np.round(g['r'].as_matrix(),2).tolist(),[np.round(x*1000,2).tolist() for x in bounds(cad/(name+'.stl'))])
 for name in ['left_eye','right_eye','bulb','flash_light_module','flash_reflector_interface','speaker_interface','speaker_stand','head']:
  print('print',name,[np.round(x,2).tolist() for x in bounds(printed/(name+'.stl'))])
PY
python model.py"
````

---

## ChatGPT（2026-11-12 00:52 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
python - <<'PY'
exec(open('model.py').read().split('mset=list')[0])
for p, g in motors.items():print(p,g[0]['body'],[(x['asset'],np.round(x['center']*1000).tolist()) for x in g])
print('joints', {j:np.round(p*1000).tolist() for j,p in joints.items()})
PY
ls -lh photos"
````

---

## ChatGPT（2026-11-12 00:52 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
python - <<'PY'
from pathlib import Path
p=Path('model.py')
s=p.read_text()
a=s.index('motors=defaultdict(list)')
b=s.index('motor_ids=',a)
s=s[:a]+'''drives=[g for g in geoms if g['asset']=='drive_palonier']
mset=[[g] for g in drives]
for g in geoms:
 if g['asset'].startswith('wj-') or g['asset']=='passive_palonier':
  i=min((i for i,h in enumerate(drives) if h['body']==g['body']),key=lambda i: np.linalg.norm(drives[i]['p']-g['p']))
  mset[i].append(g)
'''+s[b:]
s=s.replace('mset=list(motors.values())\\n','')
p.write_text(s)
PY
python model.py
curl -fLsS --max-time 10 https://cdn.jsdelivr.net/npm/fflate@0.8.2/umd/index.js -o inspect/fflate.js &
curl -fLsS --max-time 10 https://cdn.jsdelivr.net/npm/three@0.160.1/LICENSE -o inspect/three-license.txt &
curl -fLsS --max-time 10 https://cdn.jsdelivr.net/npm/fflate@0.8.2/LICENSE -o inspect/fflate-license.txt &
wait"
````

---

## ChatGPT（2026-11-12 00:52 UTC）

上游模型已對到 14 顆主舵機的安裝位置和 ID。足底開關、部分電子配件和線材需要用示意模型補上，我會在頁面逐項標明，並附原作者的照片和接線圖。

---

## ChatGPT（2026-11-12 00:56 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > build.py <<'PY'
import base64, gzip, json, re
from collections import Counter
from pathlib import Path
import numpy as np
from model import root,cad,printed,bounds,mesh,geoms,assignments,motor_ids,joints,base_rot

def b64(data):
 return base64.b64encode(data).decode()

geometry={}
def encode(key, file, units):
 if key in geometry:return
 coords=mesh(file)['verts'].reshape(-1,3).astype('float64')*units
 q=np.round(coords*100)
 assert np.abs(q).max()<32767, (key,np.abs(q).max())
 verts,inds=np.unique(q.astype('<i2'),axis=0,return_inverse=True)
 inds=inds.astype('<u2' if len(verts)<65536 else '<u4')
 geometry[key]=[len(verts),len(inds),inds.itemsize,b64(gzip.compress(verts.tobytes()+inds.tobytes(),compresslevel=5,mtime=0))]
 return key
floor=min(g['p'][1]*1000+bounds(cad/(g['asset']+'.stl'))[0][2]*1000
 for g in geoms if g['asset']=='foot_bottom_tpu')
def xyz(p):
 return np.round(p*1000-[0,floor,0],3).tolist()
def shape(g, custom=None,units=1000):
 a=g['asset']
 f=custom or cad/(a+'.stl')
 encode(a,f,units)
 return {'m':a,'p':xyz(g['p']),'q':np.round(g['r'].as_quat(),7).tolist()}

meta_print={
 'foot_top':('腳部上座',2),'foot_side':('腳部側板',2),
 'foot_bottom_pla':('硬質腳底',2),'foot_bottom_tpu':('柔軟腳墊',2),
 'knee_to_ankle_left_sheet':('腿段左側板',3),'knee_to_ankle_right_sheet':('腿段右側板',3),
 'leg_spacer':('腿段間隔件',3),'left_roll_to_pitch':('左髖關節轉接座',5),'right_roll_to_pitch':('右髖關節轉接座',5),
 'roll_motor_top':('髖側擺舵機上座',5),'roll_motor_bottom':('髖側擺舵機下座',5),
 'trunk_bottom':('主軀幹下座',1),'trunk_top':('主軀幹上座',1),
 'neck_left_sheet':('頸部左側板',6),'neck_right_sheet':('頸部右側板',6),
 'head_pitch_to_yaw':('頭俯仰／偏航轉接件',7),'head_yaw_to_roll':('頭偏航／側擺轉接件',7),'head_roll_mount':('頭部側擺支座',7),
 'head':('頭殼',10),'head_bot_sheet':('頭部底板',7),'left_antenna_holder':('左天線座',10),'right_antenna_holder':('右天線座',10),
 'left_cache':('左腿側蓋',11),'right_cache':('右腿側蓋',11),
 'body_front':('機身前殼',11),'body_middle_bottom':('機身中段下殼',11),
 'body_middle_top':('機身中段上殼',7),'body_back':('機身後殼／電池艙',9),'battery_pack_lid':('電池艙蓋',9),
 'left_eye':('左眼蓋',10),'right_eye':('右眼蓋',10),'bulb':('眼燈內片',10),
 'flash_light_module':('側邊投影燈模組座',10),'flash_reflector_interface':('投影反光杯轉接件',10),
 'speaker_interface':('喇叭轉接板',10),'speaker_stand':('喇叭支架',10),
}
counts={k:int(n) for k,n in re.findall(r'([\\w_]+)\\.stl x(\\d+)',(root/'docs/print_guide.md').read_text())}
assert set(counts)==set(meta_print) and sum(counts.values())==51
shells={'head','head_bot_sheet','body_middle_top','body_middle_bottom','body_front','body_back','battery_pack_lid','left_cache','right_cache','left_eye','right_eye'}
expressions={'left_eye','right_eye','bulb','flash_light_module','flash_reflector_interface','speaker_interface','speaker_stand'}
bom={}
parts=[]
counter=Counter()
colors=dict(outer='#eee7d9',core='#44576a',joints='#567184',rubber='#26333f',motor='#3b4a5b',metal='#a4adbc',electronics='#209781',battery='#659deb',optional='#b98964',hardware='#b28b43',wire='#d26152')
def row(k, name, cat, quantity, spec, note='',link='',opt=False):
 bom[k]=dict(k=k,name=name,cat=cat,qty=quantity,spec=spec,note=note,link=link,opt=opt)
def part(k, name, cat, st, zone, sh, center, src, col, **extra):
 counter[k]+=1
 i=extra.pop('id',k+'-'+str(counter[k]))
 parts.append(dict(id=i,k=k,name=name,cat=cat,stage=st,zone=zone,sh=sh,c=center,src=src,color=col,**extra))
 return parts[-1]
github='https://github.com/apirrone/Open_Duck_Mini'
pin='b23317a485b3cec7d8417f352478778b3475173c'
blob=github+'/blob/'+pin
for k,(name,st) in meta_print.items():
 opt=k in expressions
 row(k,name,'print',counts[k],k+'.stl · '+('TPU 40%' if k=='foot_bottom_tpu' else 'PLA 15%'),
     '原作者列印清單中的外觀／表情零件。' if opt else '',blob+'/print/'+k+'.stl',opt)
def position_zone(g,st):
 a,b=g['asset'],g['body']
 if st==2: return '左腳' if g['center'][0]>0 else '右腳'
 if st in [3,4,5]: return ('左' if g['center'][0]>0 else '右')+{3:'小腿',4:'大腿',5:'髖部'}[st]
 if st==6:return '頸部'
 if st==7 and a"'!='"'body_middle_top':return '頭部關節'
 if st==10:return '頭部'
 if st==9:return '後方電池艙'
 if a.endswith('_cache'):return ('左' if g['center'][0]>0 else '右')+'腿外側'
 return '軀幹'
def printable(g,key,custom=None):
 name,st=meta_print[key]
 if st==3 and g['body'] in ('knee_and_ankle_assembly','knee_and_ankle_assembly_3'):st=4
 col='outer' if key in shells else 'joints' if st in [5,6,7] else 'core'
 if key=='foot_bottom_tpu':col='rubber'
 if key in ('left_eye','right_eye'):col='rubber'
 if key in expressions and key not in shells:col='optional'
 zone=position_zone(g,st)
 return part(key,name,'print',st,zone,[shape(g,custom,1 if custom else 1000)],xyz(g['center']),
   'print-placement' if custom else 'cad',colors[col],cover=key in shells,opt=key in expressions)
for g in geoms:
 a=g['asset']
 key=a.removeprefix('left_') if a.startswith('left_knee_to_ankle_') else a
 if key in meta_print:printable(g,key)
head=next(g for g in geoms if g['asset']=='head')
for a in sorted(expressions):
 f=printed/(a+'.stl')
 lo,hi=bounds(f)
 printable(dict(head,asset=a,center=head['p']+head['r'].apply((lo+hi)/2000)),a,f)
assert all(counter[k]==n for k,n in counts.items())

row('sts','Feetech STS3215-C001','motor',14,'7.4 V · 1:345 · 串列匯流排',
    '主舵機與原 CAD 的主動／被動舵盤合併顯示。ID 按原作者設定。',blob+'/docs/configure_motors.md')
motor_names={'hip_yaw':'髖偏航','hip_roll':'髖側擺','hip_pitch':'髖俯仰','knee':'膝','ankle':'腳踝',
 'neck_pitch':'頸俯仰','head_pitch':'頭俯仰','head_yaw':'頭偏航','head_roll':'頭側擺'}
for j,mid in sorted(motor_ids.items(),key=lambda t:t[1]):
 side, name=('左',j[5:]) if j.startswith('left_') else ('右',j[6:]) if j.startswith('right_') else ('',j)
 st={'ankle':2,'knee':3,'hip_pitch':4,'hip_yaw':5,'hip_roll':5,'neck_pitch':6}.get(name,7)
 loc='軀幹' if name in ('hip_yaw','neck_pitch') else '頭部關節' if not side else side+motor_names[name]
 gs=assignments[j]
 center=np.mean([g['center'] for g in gs],axis=0)
 assert len(gs)==5 and np.linalg.norm(gs[0]['center']-joints[j])<.004
 part('sts',side+motor_names[name]+'舵機','motor',st,loc,[shape(g) for g in gs],xyz(center),'cad',colors['motor'],
   id='servo-'+str(mid),motor=mid,detail=j)
row('horns','主動／被動舵盤及原配固定螺絲','hardware','依 14 顆舵機附件','沿用舵機隨附件','舵盤外形已併入各 STS3215 3D 群組。模型未逐顆配置所有固定螺絲。')
row('antenna_servo','天線微型定位舵機','motor',2,'9 g 級定位舵機 · MG90S 或同尺寸',
    '上游以 SG90 外形表示，選用實物後核對耳座和舵盤。')
row('antenna','天線桿','hardware',2,'原 CAD 有外形，材料依實際安裝','CAD 有兩支天線桿，但原 51 件列印清單未另列。')
row('bearing','6804ZZ 軸承','hardware',3,'20 × 32 × 7 mm','軀幹兩顆、頭部一顆。')
row('driver','Waveshare Bus Servo Adapter (A)','electronic',1,'USB-C 資料 · 2S 舵機電源','主板位置沿用 CAD 通用板外形，接頭為示意。','https://docs.waveshare.com/Bus_Servo_Adapter_A/FAQ')
row('imu','BNO055 IMU','electronic',1,'Adafruit #2472 · I²C','依組裝圖確認板子方向，之後於 Runtime 核對姿態。',blob+'/docs/assembly_guide.md#mount-the-imu')
row('pi','Raspberry Pi Zero 2 W','electronic',1,'原版裝在頭殼內','上游網格為 Pi Zero 系列外形。')
row('sd','microSD 卡','electronic',1,'32 GB A1 建議','插入 Pi 的卡槽，外形與定位為示意。')
row('header','40-pin GPIO 排針','electronic',1,'2 × 20、2.54 mm','已焊排針版本可沿用。排針顯示為示意。')
row('battery','18650 高放電電芯','power',2,'Molicel P30B 3000 mAh 或同規格','原圖兩顆串聯，2S 標稱 7.4 V，滿電 8.4 V。')
row('holder','雙節 18650 電池座','power',1,'可接兩節串聯的中點','對照實際座體、端子與電池艙尺寸。')
row('bms','2S BMS 保護板','power',1,'2 串鋰離子，配合 8.4 V','核對實物標示 B−／BM／B+ 以及 P+/P−。')
row('charger','USB-C 2S 充電板','power',1,'USB 5 V 輸入、8.4 V 充電','Adeept 或同規格，核對實物孔位。')
row('switch','電源開關','power',1,'核對 DC 額定與開孔','在原作者接線圖中切換負載電源。')
row('ubec','5 V UBEC 降壓','power',1,'2S 輸入 → 5 V 給 Pi','以 CAD 頭內通用板位置和示意外形呈現，安裝位置依實物與線長。')
cadmap={'roll_bearing':'bearing','usb_c_charger':'charger','power_switch':'switch','bms':'bms','bno055':'imu','cell':'battery','holder':'holder','raspberrypizerow':'pi','sg90':'antenna_servo','antenna':'antenna'}
for g in geoms:
 a=g['asset']
 k=('ubec' if g['body']=='head_assembly' else 'driver') if a=='board' else cadmap.get(a)
 if not k:continue
 # The second generic board is shown as a UBEC reference, not as verified model identity.
 st=9 if bom[k]['cat']=='power' and k"'!='"'ubec' else 10 if g['body']=='head_assembly' or a=='antenna' else 8
 if k=='bearing':st=10 if g['body']=='head_assembly' else 1
 zone='後方電池艙' if st==9 else '頭部' if st==10 else '軀幹'
 name=bom[k]['name']
 if k in {'antenna','antenna_servo'}:name=('左' if g['center'][0]>0 else '右')+name
 src='proxy' if a in ('board','sg90','raspberrypizerow') else 'cad'
 col='metal' if k=='bearing' else 'battery' if k=='battery' else 'motor' if k=='antenna_servo' else 'electronics' if bom[k]['cat']=='electronic' or k in ('ubec','bms','charger') else 'hardware'
 sh=[shape(g)]
 center=xyz(g['center'])
 if k=='driver':
  for i in (-10,0,10):
   sh.append(dict(box=[6,5,5],p=[center[0]+i,center[1]+3,center[2]+16],color='#d6e5de'))
  sh.append(dict(box=[9,4,7],p=[center[0]-7,center[1]+3,center[2]-17],color='#a6b6c8'))
 if k=='ubec':
  sh.append(dict(box=[22,8,30],p=[center[0],center[1]-5,center[2]],color='#3f847a'))
 part(k,name,bom[k]['cat'],st,zone,sh,center,src,colors[col])

def box(pos,size,col=None):
 return dict(box=size,p=pos,**({'color':col} if col else {}))
def cyl(pos,r,length,axis='y',col=None):
 return dict(cyl=[r,length,axis],p=pos,**({'color':col} if col else {}))
def proxy(k,name,st,zone,pos,sh=None,size=None,col=None,**extra):
 b=bom[k]
 return part(k,name,b['cat'],st,zone,sh or [box(pos,size)],pos,'proxy',col or colors.get(b['cat'],'#ba9966'),opt=b['opt'],**extra)
pi=next(p for p in parts if p['k']=='pi')['c']
proxy('sd','microSD 卡',10,'Pi Zero 卡槽',[pi[0],pi[1]-2,pi[2]-32],size=[11,1,15],col='#30394c')
header=[pi[0]-12,pi[1]-3,pi[2]]
proxy('header','40-pin GPIO 排針',10,'Pi Zero 側邊',header,sh=[box(header,[5,2,50],'#242c37')]+[
 cyl([header[0]+d,header[1]-2,header[2]+(i-9.5)*2.54],.38,4,'y','#dfb259') for d in (-1.27,1.27) for i in range(20)])
row('foot_switch','Omron SS-10 足底開關','electronic',4,'按柱型，BOM 採購 4 顆',
    '原圖每腳展示 1 顆，3D 顯示兩個安裝位置。其餘可作備品。',blob+'/docs/assembly_guide.md#assemble-the-feet')
for x,side in [(90,'左'),(-91,'右')]:
 p=[x,9,-2]
 proxy('foot_switch',side+'足底開關',2,side+'腳內部',p,sh=[box(p,[19.8,8,6.4],'#2d3542'),cyl([x,4,-2],1.45,4,'y','#e2b66c')]+[
  box([x+i,15,-2],[1.1,5,2],'#c9c5ab') for i in [-6,0,6]])
row('xt30','XT30 公母接頭','power','1 對','電池組快拆','接頭及走線為示意。')
row('dc','DC 5.5 × 2.1 mm 插頭','power',2,'依 BOM 買 2 個','實際插頭極性以接線圖和實物檢查。')
row('usb15','短 Micro-USB ↔ USB-C 線','wire',1,'15 cm · 原 BOM','線路僅展示對照用途，實際選擇須支援資料／OTG。')
row('usb50','長 Micro-USB ↔ USB-C 線','wire',1,'50 cm · 原 BOM','Pi 資料孔連到機身舵機板；以實際繞線長度挑選。')
row('bus_wires','Feetech 三芯匯流排線','wire','依走線','資料／舵機電源／GND','頭頸、左右腿串接。示意路徑只供辨識。')
row('power_wire','紅黑電源線','wire','依走線','2S 原電壓支路與 5 V 支路','顯示為示意線路，請對照原接線圖與實物。')
row('signal_wire','IMU／足底／天線訊號線','wire','依走線','I²C、GPIO、PWM','虛擬線路不表示實際線長或端子方向。')
row('sheath','束線套、熱縮套管及束線帶','hardware','依用量','原 BOM 列 1 份束線套','分段保護焊點與固定線束。')
for x in (7,17):
 proxy('xt30','XT30 '+('公頭' if x==7 else '母頭'),9,'電池艙接線',[x,249,-94],size=[9,6,12],col='#edb534')
for idx,p in enumerate(([7,258,-66],[21,251,-85]),1):
 proxy('dc','DC5521 插頭 '+str(idx),9,'電池艙與機身',p,sh=[cyl(p,4.8,14,'z','#202c39'),cyl([p[0],p[1],p[2]+9],2.75,7,'z','#afb8c2')])
def route(k,n,st,p,col):
 part(k,n,'wire',st,'線路示意',[{'tube':p}],p[len(p)//2],'route',col)
route('usb50','Pi USB 資料孔 → 舵機板',12,[[46,420,31],[23,398,0],[12,348,-13],[7,296,-61],[2,258,-83]],'#8c79ce')
route('usb15','短 USB 線（原 BOM 備用長度）',12,[[44,415,24],[28,407,5],[13,391,1]],'#b792ed')
for side in [1,-1]:
 route('bus_wires',('左' if side==1 else '右')+'腿舵機總線',12,[[0,256,-84],[24*side,239,-49],[38*side,217,-29],[96*side,177,-39],[95*side,118,-38],[93*side,46,-36]],'#df9b44')
route('bus_wires','頭頸舵機總線',12,[[0,257,-82],[1,268,-34],[-3,303,-8],[-5,356,4],[2,397,45]],'#df9b44')
route('power_wire','2S → 驅動板',12,[[-24,224,-123],[-13,237,-109],[0,249,-94],[8,255,-79]],'#df6356')
route('power_wire','2S → UBEC → Pi 5 V',12,[[15,251,-102],[19,271,-67],[24,315,-22],[18,374,14],[-53,420,59],[48,425,35]],'#db675e')
route('signal_wire','BNO055 I²C → Pi',12,[[2,240,-86],[25,253,-69],[26,312,-11],[31,370,20],[42,419,34]],'#39b4a6')
for x in [-1,1]:
 route('signal_wire',('左' if x>0 else '右')+'腳接地開關 → Pi GPIO',12,[[90*x,9,-2],[90*x,42,-19],[88*x,120,-25],[41*x,204,-19],[12*x,286,-13],[32,418,34]],'#4e9cce')
 route('signal_wire',('左' if x>0 else '右')+'天線舵機 PWM',12,[[48*x,388,-63],[33*x,413,-32],[36,422,35]],'#4e9cce')

row('screw6','M3×6 機械牙螺絲','hardware','至少 4 支','兩腳底各 2 支','顯示腳底位置示意。依原圖確認實際頭型與孔位。')
row('screw10','M3×10 機械牙螺絲','hardware','至少 2 支','主軀幹上／下座至少 2 支','顯示代表位置。')
row('screws','其餘 M3 螺絲與舵機原配螺絲','hardware','原作者未列總數','依組裝位置選長度與頭型','裝配用耗材，原作者未提供逐孔規格。')
row('inserts','M3 熱熔銅螺母','hardware','依孔位 · BOM 1 包','先量列印孔的外徑與深度','標示腳部、腿部間隔件、軀幹和頭殼的代表位置。未逐孔建模。')
row('lock','Loctite 243','hardware',1,'螺紋固定劑','原作者建議用於舵機的金屬對金屬螺絲。')
for x in (-91,90):
 for i,z in enumerate((-35,11)):
  p=[x,5,z]
  proxy('screw6','腳底螺絲 '+str(i+1),2,'腳底',p,sh=[cyl(p,1.5,6),cyl([x,1,z],2.8,2)],col='#b9a9a1')
for x in (-29,29):
 p=[x,259,13]
 proxy('screw10','軀幹螺絲',1,'主軀幹',p,sh=[cyl(p,1.5,10),cyl([x,265,13],2.8,2)],col='#b9a9a1')
for idx,(x,y,z,st,zone) in enumerate([(-91,11,11,2,'腳部'),(90,11,11,2,'腳部'),(-91,93,-38,3,'腿段'),(90,93,-38,3,'腿段'),(-91,163,-38,4,'腿段'),(90,163,-38,4,'腿段'),(-29,248,13,1,'軀幹'),(29,248,13,1,'軀幹'),(67,380,47,10,'頭殼'),(-67,380,47,10,'頭殼')],1):
 p=[x,y,z]
 proxy('inserts','M3 熱熔銅螺母（示意）',st,zone,p,sh=[{'ring':[2.3,1.45,4.5],'p':p}],col='#d6a15a')
optional=[
 ('cam','Pi 相機模組',1,'Pi Zero 相容 CSI 相機及對應排線','原 BOM 列為未整合配件。近前面板的位置是示意，需以實際相機與鏡頭開孔決定。',[0,408,103],[24,23,7]),
 ('amp','MAX98357A I²S 放大器',1,'I²S 喇叭驅動模組','原作者有列 I²S 接腳。模組在頭內，位置參考照片。',[-76,416,31],[18,4,22]),
 ('mic','USB 麥克風',1,'選購，依頭殼空間與接頭','原 BOM 註明尚未整合。',[24,416,77],[14,7,8]),
 ('speaker','小型喇叭',1,'核對喇叭支架的尺寸','位置參考原作者頭殼內部照片。',[-65,398,23],None),
 ('reflector','投影反光杯',1,'搭配側邊投影燈模組座','依原印件的大致位置顯示。',[96,404,91],None),
 ('led','眼燈與投影 LED',3,'左眼、右眼與投影各 1 顆','接腳可在網頁的接線頁查閱。',None,None),
 ('diffuser','眼燈擴散片',4,'原 BOM 估 4 片','依實際燈具組合；3D 以薄片表示。',None,None),
]
for k,name,count,spec,note,pos,size in optional:
 row(k,name,'electronic',count,spec,note,opt=True)
 if size:proxy(k,name,10,'頭部',pos,size=size,col='#379b86')
 if k in ('speaker','reflector'):
  axis='x'
  proxy(k,name,10,'頭部',pos,sh=[cyl(pos,18 if k=='speaker' else 10,8,axis,'#43515c'),
    cyl([pos[0]+(-4 if k=='speaker' else 4),pos[1],pos[2]],14 if k=='speaker' else 7,2,axis,'#c4b6a1')])
 if k=='led':
  for i,(x,y,z) in enumerate([(40,401,101),(-40,401,101),(97,405,91)],1):
   p=[x,y,z]
   proxy(k,name+' '+str(i),10,'頭部',p,sh=[cyl(p,2.6,6,'z')],col='#f5c956')
 if k=='diffuser':
  for x in (-40,40):
   for z in (103,106):
    p=[x,401,z]
    proxy(k,name,10,'眼部',p,sh=[cyl(p,13,1,'z')],col='#b8d4d8')
row('csi','Pi Zero 相機排線','wire',1,'Pi Zero 端用窄版 CSI 排線','選配，實際配線長度按鏡頭位置。',opt=True)
route('csi','相機 CSI 排線',10,[[0,410,100],[10,420,82],[33,426,56],[47,424,34]],'#e3d4aa')
parts[-1]['opt']=True
row('controller','藍牙 Xbox 相容手把','hardware','依需求','Runtime 有對應 Xbox 控制範例','手把與電烙鐵、萬用電表等為外部工具。','https://github.com/apirrone/Open_Duck_Mini_Runtime/tree/v2')
assert len({p['id'] for p in parts})==len(parts)
assert set(p['k'] for p in parts)<=set(bom)
assert sum(1 for p in parts if p['k']=='sts')==14
assert all(k in geometry for p in parts for k in [s['m'] for s in p['sh'] if 'm' in s])
docs=root/'docs'
photos={}
for f in Path('photos').glob('*.jpg'):
 photos[f.stem]='data:image/jpeg;base64,'+b64(f.read_bytes())
for name,path in [('system-wiring','open_duck_mini_v2_wiring_diagram.png'),('wiring-detail','wiring.png')]:
 photos[name]='data:image/png;base64,'+b64((docs/path).read_bytes())
print('models',len(geometry),'objects',len(parts),'BOM',len(bom),'photos',len(photos),'triangles',sum(x[1]//3 for x in geometry.values()))
data=dict(geometry=geometry,parts=parts,bom=list(bom.values()),photos=photos,commit=pin)
def jsjson(data):
 return json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('</','<\\\\/')
page=Path('index.template').read_text()
licenses='Open Duck Mini v2 — Antoine Pirrone and contributors\\n\\n'+(root/'LICENSE').read_text()
for name in ['three','fflate']:
 licenses+='\\n\\n'+Path('inspect/'+name+'-license.txt').read_text()
for token, content in {
 'STYLE':Path('viewer.css').read_text(),'THREE':Path('inspect/three.min.js').read_text(),
 'FFLATE':Path('inspect/fflate.js').read_text(),'DATA':jsjson(data),'GUIDE':Path('guide.js').read_text(),
 'VIEWER':Path('viewer.js').read_text(),'LICENSES':jsjson(licenses),
}.items():
 page=page.replace('{{'+token+'}}',lambda_value if False else content,1)
dest=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html')
dest.write_text(page)
print(dest,dest.stat().st_size)
PY
sed -i 's/lambda_value if False else content/content/' build.py
ls -lh inspect/{three.min.js,fflate.js,three-license.txt,fflate-license.txt}"
````

---

## ChatGPT（2026-11-12 00:57 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > guide.js <<'JS'
const REPO = 'https://github.com/apirrone/Open_Duck_Mini';
const UP = REPO + '/blob/' + DATA.commit + '/docs/';
const RUNTIME = 'https://github.com/apirrone/Open_Duck_Mini_Runtime/tree/v2';
const BOM_URL = 'https://docs.google.com/spreadsheets/d/1gq4iWWHEJVgAA_eemkTEsshXqrYlFxXAPwO515KpCJc/edit';
const steps = [
  { title:'舵機編號與零位', summary:'每次只接一顆 STS3215，先寫 ID、再對零。',
    tasks:['使用 Open Duck Mini Runtime 的 v2 分支，按原作者指引執行 configure_motor.py --id <ID>。每次接一顆，記下 ID 並貼在舵機外殼。','零位動作完成後，再依照片裝舵盤。以鴨子自身的左右辨識腿部。','核對右腿 10–14、左腿 20–24、頭頸 30–33。點 BOM 的舵機可查每顆位置。'],
    check:'14 顆均可單獨通訊，ID 唯一，零位及裝配朝向已記錄。', pics:[['servo-zero','舵機與舵盤零位']], src:UP+'configure_motors.md', tip:'先做桌上通訊測試，再把舵機鎖進機構。' },
  { title:'主軀幹與兩顆軸承', summary:'先裝軸承與熱熔螺母，再合上主軀幹。',
    tasks:['把兩顆 6804ZZ 壓入 trunk_bottom。按原圖裝熱熔螺母，包含底面後續鎖殼的四個孔。','對合 trunk_top 與 trunk_bottom，用兩支 M3×10 固定。','安裝位於中央的頸俯仰舵機 ID 30。原圖所示塑膠固定螺絲沿用舵機配件。'],
    check:'軸承就位，兩個軀幹件接合平整。', pics:[['trunk-bearings','軸承與嵌件位置'],['trunk-screws','兩支 M3×10 的鎖點']], src:UP+'assembly_guide.md#assemble-the-trunk', include:['servo-30'] },
  { title:'兩隻腳與足底開關', summary:'先鎖腳底，再固定腳踝舵機與觸地開關。',
    tasks:['每隻腳將硬質 PLA 腳底與 TPU 腳墊疊合，以兩支 M3×6 鎖上。','在 foot_top 裝熱熔螺母。腳踝舵機 ID 14／24 的主動側朝 foot_top，對照原圖辨識兩側。','依照片壓入 SS-10，確認腳掌著地時能觸發。BOM 採購四顆，組裝圖每腳示範一顆。'],
    check:'腳掌可平貼桌面，按下腳底時開關有動作。', pics:[['foot-bottom','腳底的兩個固定點'],['foot-fit','腳踝舵機朝向'],['foot-switch','SS-10 壓入位置']], src:UP+'assembly_guide.md#assemble-the-feet' },
  { title:'小腿、膝與穿線', summary:'先穿腳踝舵機線，再鎖小腿側板。',
    tasks:['每個小腿間隔件兩側各有兩個熱熔螺母孔。準備左右各一片側板。','先把線插到腳踝舵機，穿過 right_sheet，再裝兩側板。','與對應膝舵機 ID 13／23 的組件對位。試轉時確認線束有餘量。'],
    check:'活動一遍腳踝與膝附近的關節，線不會被側板夾住。', pics:[['shin-inserts','間隔件螺母孔'],['shin-wire','腳踝線穿過右側板']], src:UP+'assembly_guide.md#assemble-the-shins', include:['servo-14','servo-24'] },
  { title:'大腿與髖俯仰零位', summary:'大腿重用側板與間隔件，注意髖俯仰朝向。',
    tasks:['每條大腿用左右側板與 leg_spacer 各一件。','將髖俯仰舵機 ID 12／22 按原圖的方向安裝。鎖定前再對照舵盤零位。','接合小腿，確認左、右腿的運動方向和零位符合 Runtime。'],
    check:'左右件與舵機 ID 相符，零位時雙腿沒有明顯偏斜。', pics:[['thigh-zero','髖俯仰舵機的零位方向']], src:UP+'assembly_guide.md#assemble-the-thighs', include:['servo-13','servo-23'] },
  { title:'髖部與雙腿上身', summary:'分清左右轉接座，先組好側擺機構。',
    tasks:['把左右對應的 roll_to_pitch 轉接座裝在髖側擺舵機 ID 11／21。','先從下方把 roll_motor_top 鎖到髖偏航舵機 ID 10／20。依圖加入 roll_motor_bottom 與側擺子總成。','把兩組髖和雙腿裝回主軀幹，按原圖確認轉接座方向。'],
    check:'雙腿固定後可在預期關節範圍內活動，舵盤、側板與外側線束無干涉。', pics:[['hip-bracket','偏航舵機與上座'],['hip-mount','腿與軀幹接合']], src:UP+'assembly_guide.md#assemble-the-hips', include:['trunk_bottom-1','trunk_top-1'] },
  { title:'頸部與頭俯仰', summary:'把兩片頸板接到頸俯仰舵機。',
    tasks:['辨識 neck_left_sheet 與 neck_right_sheet。將頸板與軀幹中央的 ID 30 接合。','按組裝圖安裝 ID 31 的頭俯仰接合端。先留好經過頸部的線路。'],
    check:'在頭殼裝上之前先確認頭頸可活動，線束沒有跨在夾點上。', pics:[['neck','頸板與舵機的位置']], src:UP+'assembly_guide.md#assemble-the-neck', include:['servo-31'] },
  { title:'頭部關節、底板與上殼', summary:'先套頭底板和機身中段上殼，再鎖定頭部關節。',
    tasks:['安裝 head_pitch_to_yaw，辨識頭偏航 ID 32 與頭側擺 ID 33。','先將 head_yaw_to_roll、head_roll_mount 與側擺端預組。','將 head_bot_sheet 與 body_middle_top 預先套進去，再完成關節連接。'],
    check:'頭部底板與中段上殼已在位，頭頸全行程試動無卡線。', pics:[['head-roll','頭側擺支座與舵機']], src:UP+'assembly_guide.md#assemble-the-head-mechanism' },
  { title:'機身控制板與 IMU', summary:'固定 Waveshare 驅動板，記錄 BNO055 朝向。',
    tasks:['在機身固定 Waveshare Bus Servo Adapter (A)，留出 USB-C 與電源端子空間。3D 板形用於辨識位置。','照原圖裝 BNO055，記下實際朝向。原作者說明照片的 IMU 是倒裝範例，Runtime 須跟實際方向一致。','把 BNO055 的 SDA／SCL 接到 Pi 的 GPIO 2／3。以接線頁核對實物端子。'],
    check:'板子與外殼之間有絕緣與端子空間，Runtime 讀到的姿態方向正確。', pics:[['imu','BNO055 的機身位置'],['system-wiring','整機接線圖']], src:UP+'assembly_guide.md#electronics' },
  { title:'2S 電池艙與供電', summary:'電池、BMS、充電板與負載開關依原圖接線。',
    tasks:['先做不帶電的定位。把電池座、BMS、USB-C 充電板與開關放入後殼，確認孔位和極性。','兩顆 18650 以 2S 串聯。按 BMS 實物和原圖核對電池中點與保護板端子。裝入前先確認電芯電壓一致。','原電壓支路給 STS3215，UBEC 的穩壓 5 V 給 Pi。接負載前用萬用表確認兩路電壓與極性。'],
    check:'2S 支路、5 V 支路與極性量測正確，後蓋可關合。', pics:[['battery','原電池艙配置'],['system-wiring','電源分流與充電']], src:UP+'assembly_guide.md#battery-pack', includeKeys:['ubec'] },
  { title:'頭內電子與天線', summary:'裝 Pi、排針、microSD、軸承和天線舵機。',
    tasks:['在頭殼裝嵌件和第三顆 6804ZZ 軸承，再裝 Pi Zero 2 W、microSD 與兩顆天線舵機。','先試放頭底板。確認 USB、GPIO 和排線仍可接，整理頭內線束後再鎖。','若裝相機、喇叭、眼燈、反光杯或麥克風，先依照片、印件與實物試裝。原指南的表情模組章節未完成。'],
    check:'頭殼可關合，天線能移動，選配模組沒有碰到頭頸關節。', pics:[['head-internal','原作者的頭部內部實拍'],['wiring-detail','原作者頭部配線示意']], src:UP+'assembly_guide.md#head' },
  { title:'機身外殼與電池艙上機', summary:'先中段下殼，再前殼、上殼、腿蓋和電池艙。',
    tasks:['先固定 body_middle_bottom，再依原圖在中段上下殼的安裝孔置入嵌件。','裝 body_middle_top、body_front 與後方電池艙。左右腿側蓋依鴨身方向配對。','外殼鎖定前，試裝電池艙蓋並查看開關和 USB-C 口。'],
    check:'外殼對位，電池艙可開啟，電源開關與充電口可操作。', pics:[['body','外殼與電池艙'],['assembled','原作者組裝完成照片']], src:UP+'assembly_guide.md#body', includeKeys:['body_middle_top','body_back','battery_pack_lid'] },
  { title:'線束檢查與 GPIO 對照', summary:'對照原接線圖，逐條核對動力、訊號與接地。',
    tasks:['核對 Pi 資料埠接到舵機板，左右腿與頭頸串列匯流排可逐段辨識。','核對足底開關、BNO055、天線 PWM 的 GPIO。若安裝燈光與聲音，再核對 LED 與 I²S。','把活動關節附近的線束留出轉動餘量，確認無夾線。3D 線條只標示連接關係。'],
    check:'電源、資料線、開關與 IMU 逐項檢查完畢，任何支路的兩端都找得到。', pics:[['system-wiring','原作者整機接線圖'],['feet-wiring','足底開關接線'],['wiring-detail','原作者詳細配線圖']], src:UP+'assembly_guide.md#electronics' },
  { title:'上電與首次動作測試', summary:'先支撐機體，在 Runtime 逐軸驗證。',
    tasks:['先支撐或架高鴨身，逐軸讀出 ID、位置和方向。確認線束與舵機不會被牽扯。','在 Runtime v2 核對 IMU 與足底狀態，再用低幅度動作確認左、右腿對應。','依原作者 Runtime 指引進行首次站立及步行。'],
    check:'所有舵機、IMU 和足底開關可讀，站立測試正常後再放到地面。', pics:[['assembled','原作者完成組裝的外觀']], src:RUNTIME }
];

const pinGroups = [
  ['BNO055 I²C', [['VIN','1','3V3'],['GND','9','GND'],['SDA','3','GPIO 2'],['SCL','5','GPIO 3']]],
  ['足底開關', [['左腳','15','GPIO 22'],['右腳','13','GPIO 27'],['GND','9','GND']]],
  ['天線舵機', [['左 PWM','32','GPIO 12'],['右 PWM','33','GPIO 13'],['電源／地','2／6','5 V／GND']]],
  ['眼燈／投影 LED', [['左眼','16','GPIO 23'],['右眼','18','GPIO 24'],['投影','22','GPIO 25'],['共地','6','GND']]],
  ['MAX98357A', [['LRC','35','GPIO 19'],['BCLK','12','GPIO 18'],['DIN','40','GPIO 21'],['GND／VIN','6／2','GND／5 V']]]
];
JS"
````

---

## ChatGPT（2026-11-12 00:59 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > index.template <<'HTML'
<"'!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Open Duck Mini v2｜3D 組裝檢視器</title>
<style>{{STYLE}}</style>
</head>
<body>
<header class="mast">
  <div class="identity"><div class="logo" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
  <div><h1>Open Duck Mini <em>v2</em></h1><p>3D 組裝檢視器</p></div></div>
  <div class="top-actions"><button id="wire-guide" class="soft">接線圖與腳位</button><button id="sources" class="quiet">來源與模型精度</button></div>
</header>
<main class="workspace">
  <aside class="panel stages" aria-labelledby="stage-heading">
    <div class="panel-head"><div><h2 id="stage-heading">組裝順序</h2><p id="progress-text">0／14 步完成</p></div></div>
    <progress id="progress" max="14" value="0" aria-label="組裝進度"></progress>
    <nav id="steps" aria-label="組裝步驟"></nav>
  </aside>
  <section class="panel viewer" aria-label="3D 工作區">
    <div class="scene-bar">
      <div class="segments" role="group" aria-label="模型模式">
        <button data-mode="assembly" aria-pressed="true">組裝</button>
        <button data-mode="exploded" aria-pressed="false">爆炸</button>
        <button data-mode="cut" aria-pressed="false">透視</button>
      </div>
      <div class="scene-actions"><button id="only-focus" aria-pressed="false" title="只顯示選取項目或目前步驟">單獨查看</button><button id="fit">置中</button></div>
    </div>
    <div id="viewport">
      <div id="scene-status" role="status">正在載入原版模型…</div>
      <div class="view-buttons" role="group" aria-label="鏡頭角度"><button data-view="iso" aria-pressed="true">斜視</button><button data-view="front" aria-pressed="false">正面</button><button data-view="back" aria-pressed="false">背面</button><button data-view="side" aria-pressed="false">側面</button></div>
      <div id="selection" aria-live="polite" hidden></div>
      <div class="gestures">拖曳旋轉 · 滾輪縮放 · 右鍵平移</div>
    </div>
    <div class="control-bar">
      <label class="slider" for="spread"><span>爆炸距離</span><input type="range" id="spread" min="0" max="100" value="0"><output id="spread-value" for="spread">0%</output></label>
      <div class="layer-options"><label><input type="checkbox" id="wires"> 線束</label><label><input type="checkbox" id="options" checked> 選配</label></div>
    </div>
    <article id="details" class="details" aria-live="polite"></article>
  </section>
  <aside class="panel bom" aria-labelledby="bom-heading">
    <div class="panel-head"><div><h2 id="bom-heading">零件清單 <small>BOM</small></h2><p id="bom-count"></p></div></div>
    <div class="bom-controls">
      <label class="search"><span aria-hidden="true">⌕</span><input id="search" type="search" placeholder="名稱、STL、型號或舵機 ID" aria-label="搜尋零件"></label>
      <div class="filter-line"><label for="category" class="sr-only">零件類別</label><select id="category"><option value="all">所有類別</option><option value="print">列印件</option><option value="motor">馬達</option><option value="electronic">電子</option><option value="power">電源</option><option value="wire">線材</option><option value="hardware">五金</option></select><label><input type="checkbox" id="step-only"> 目前步驟</label></div>
    </div>
    <div id="bom-list"></div>
    <div class="bom-foot"><span class="dot cad"></span> 原版模型 <span class="dot proxy"></span> 位置或外形示意</div>
  </aside>
</main>
<dialog id="dialog"><div class="dialog-head"><h2 id="dialog-title"></h2><button id="close-dialog" aria-label="關閉">關閉</button></div><div id="dialog-content"></div></dialog>
<script>{{THREE}}</script>
<script>{{FFLATE}}</script>
<script>const DATA={{DATA}}; const LICENSES={{LICENSES}};</script>
<script>{{GUIDE}}</script>
<script>{{VIEWER}}</script>
</body>
</html>
HTML
cat > viewer.css <<'"'CSS'
:root{--background:#0b131d;--panel:#101b28;--surface:#162334;--line:#283a4e;--text:#e7edf3;--muted:#a0b2c5;--mint:#7ce0c5;--mint-dim:#153a37;--blue:#8cb9ed;--amber:#e9bd83;--radius:12px;font-family:Inter,\"PingFang TC\",\"Noto Sans CJK TC\",\"Microsoft JhengHei\",system-ui,sans-serif;color:var(--text);background:var(--background)}
*{box-sizing:border-box}
body{margin:0;min-width:320px}
button,input,select{font:inherit}
button,select{border:1px solid var(--line);border-radius:7px;color:var(--text);background:var(--surface)}
button{cursor:pointer;min-height:34px;padding:5px 11px}
button:hover:not(:disabled),select:hover{background:#21324a;border-color:#4a647e}
button[aria-pressed=true]{color:var(--mint);border-color:#4a897d;background:var(--mint-dim)}
button:disabled{opacity:.42;cursor:default}
:focus-visible{outline:2px solid var(--mint);outline-offset:3px}
a{color:#98c9ff;text-decoration:none}a:hover{text-decoration:underline}
input[type=checkbox],input[type=range]{accent-color:var(--mint)}
h1,h2,h3,p{margin:0}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.mast{min-height:80px;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;gap:14px;border-bottom:1px solid var(--line);background:#101a27}
.identity,.top-actions,.segments,.scene-actions,.layer-options,.view-buttons{display:flex;align-items:center;gap:8px}
.identity{gap:14px}
.logo{display:grid;grid-template-columns:repeat(2,9px);gap:4px;padding:9px;border:1px solid #366659;border-radius:9px;background:#142f32;transform:rotate(-5deg)}
.logo span{height:9px;background:var(--mint);border-radius:2px}.logo span:nth-child(2){background:#428b80}.logo span:nth-child(3){background:#428b80}
h1{font-size:25px;font-weight:740;letter-spacing:-.035em;line-height:1.13}
h1 em{font-style:normal;color:var(--mint);font-size:.62em;padding-left:4px;letter-spacing:0}
.identity p{font-size:12px;margin-top:4px;color:var(--muted);letter-spacing:.08em}
.top-actions button{font-size:13px}
.quiet{background:transparent}
.workspace{display:grid;grid-template-columns:minmax(175px,218px) minmax(0,1fr) minmax(245px,325px);gap:12px;padding:14px;max-width:1800px;margin:0 auto;align-items:start}
.panel{border:1px solid var(--line);background:var(--panel);border-radius:var(--radius);min-width:0}
.panel-head{display:flex;align-items:center;justify-content:space-between;padding:16px 15px 9px}
.panel-head h2{font-size:16px;line-height:1.35;font-weight:700}
.panel-head small{font-size:10px;letter-spacing:.09em;color:var(--mint);margin-left:5px}
.panel-head p{font-size:12px;color:var(--muted);margin-top:5px;line-height:1.35}
.stages,.bom{position:sticky;top:12px}
#progress{width:calc(100% - 30px);height:4px;margin:2px 15px 11px;border:0;appearance:none;display:block}
#progress::-webkit-progress-bar{background:#223145;border-radius:5px}
#progress::-webkit-progress-value{background:var(--mint);border-radius:5px}
#progress::-moz-progress-bar{background:var(--mint);border-radius:5px}
#steps{padding:0 8px 8px;max-height:calc(100vh - 195px);overflow:auto;scrollbar-width:thin}
.step{display:flex;width:100%;align-items:center;text-align:left;gap:8px;margin:2px 0;padding:7px 6px;background:transparent;border-color:transparent;font-size:13px;line-height:1.4}
.step .number{width:25px;flex:0 0 25px;height:24px;border-radius:5px;display:grid;place-items:center;font-family:\"IBM Plex Mono\",ui-monospace,monospace;font-size:11px;color:var(--muted);background:#1c2a3a}
.step .done{color:var(--mint);margin-left:auto}
.step[aria-current=step]{background:#16312f;border-color:#33574f;color:#c7f7e8}
.step[aria-current=step] .number{color:#0e2524;background:var(--mint)}
.viewer{overflow:hidden}
.scene-bar,.control-bar{display:flex;justify-content:space-between;align-items:center;padding:9px 11px;gap:8px}
.scene-bar button,.control-bar,.view-buttons button{font-size:12px}
.scene-bar button{white-space:nowrap}
#viewport{height:clamp(360px,56vh,690px);position:relative;isolation:isolate;background:radial-gradient(ellipse at 48% 40%,#21354a 0%,#142233 60%,#0f1b28 100%);overflow:hidden;border-block:1px solid var(--line)}
#viewport canvas{position:absolute;inset:0;display:block;width:100%;height:100%;touch-action:none;cursor:grab;z-index:0}
#viewport canvas:active{cursor:grabbing}
#scene-status{position:absolute;inset:45% 20px auto;text-align:center;z-index:2;color:#c4d8ed;pointer-events:none;font-size:13px}
.view-buttons{position:absolute;z-index:2;top:10px;right:10px;gap:4px}
.view-buttons button{background:#122233df;min-height:29px;padding-inline:7px;color:#b9c9d9}
.view-buttons button[aria-pressed=true]{background:#264746;color:#a9f1de}
.gestures{position:absolute;right:10px;bottom:9px;z-index:1;color:#abbed0;font-size:11px;pointer-events:none;background:#102033d9;border-radius:4px;padding:4px 6px}
#selection{position:absolute;bottom:29px;left:11px;max-width:calc(100% - 22px);z-index:2;background:#102131ef;border:1px solid #487b75;border-radius:7px;padding:8px 10px;font-size:12px;line-height:1.45}
#selection strong{display:block;color:#b9f0e1}
#selection p{color:#afc4d6;margin-top:3px}
.control-bar{border-bottom:1px solid var(--line);flex-wrap:wrap}
.slider{display:flex;align-items:center;gap:8px;flex:1;min-width:150px;color:var(--muted)}
.slider input{flex:1;max-width:270px;min-width:65px}
.slider output{min-width:35px;color:var(--mint);font-variant-numeric:tabular-nums}
.layer-options label,.filter-line label{display:flex;align-items:center;gap:3px;white-space:nowrap;color:var(--muted);cursor:pointer}
.layer-options{gap:9px}
.details{padding:15px;min-height:225px}
.details h2{font-size:18px;line-height:1.4}
.details .intro{color:#bdcbd8;font-size:13px;line-height:1.6;margin-top:6px}
.details ol{margin:10px 0 10px;padding-left:23px;color:#dde6ee;font-size:13px;line-height:1.65}
.details li{padding:2px 0}
.details .reference{color:var(--muted);font-size:12px;line-height:1.6;margin-top:8px}
.details .reference a{margin-right:12px}
.checkline{margin-top:11px;border-left:2px solid var(--mint);background:#182c34;padding:8px 10px;color:#c8e9e2;line-height:1.55;font-size:12px}
.step-bottom{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap}
.step-bottom div{display:flex;gap:6px}
.step-bottom button{font-size:12px}
.step-bottom .complete{background:#153b37;color:var(--mint);border-color:#3b6d63}
.gallery{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}
.thumb{background:#18283a;padding:4px;display:grid;gap:4px;justify-items:center;width:94px;font-size:10px;line-height:1.3}
.thumb img{width:84px;height:51px;object-fit:cover;border-radius:4px;background:#e7e9e7}
.bom-controls{padding:2px 12px 9px}
.search{display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:7px;padding:3px 9px;background:#0d1824;color:var(--mint);font-size:18px}
.search input{width:100%;background:none;border:none;color:var(--text);padding:5px 0;font-size:12px;min-width:0}
.search input:focus{outline:none}
.search:focus-within{border-color:#69a59b}
.search input::placeholder{color:#90a6bb}
.filter-line{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:8px;font-size:12px}
.filter-line select{max-width:50%;padding:5px 7px}
#bom-list{padding:0 8px;max-height:calc(100vh - 257px);min-height:170px;overflow:auto;scrollbar-width:thin}
.bom-row{width:100%;border:0;border-bottom:1px solid #223448;background:transparent;display:grid;grid-template-columns:9px minmax(0,1fr) auto;align-items:start;gap:7px;text-align:left;min-height:47px;padding:8px 6px;border-radius:4px}
.bom-row[aria-pressed=true]{background:#183837;box-shadow:inset 0 0 0 1px #3d756a}
.bom-row strong{font-size:12px;line-height:1.3;display:block;overflow-wrap:anywhere;font-weight:650}
.bom-row small{font-size:10px;color:#a2b5c8;line-height:1.4;overflow-wrap:anywhere;display:block;margin-top:3px}
.qty{font:10px/1.3 \"IBM Plex Mono\",ui-monospace,monospace;color:#b8c9d8;background:#243549;border-radius:4px;padding:3px 4px;max-width:78px;text-align:right}
.dot{width:7px;height:7px;display:inline-block;border-radius:50%;background:#7799ba;flex:none}
.bom-row .dot{margin-top:4px}
.dot.motor{background:#9caff5}.dot.electronic{background:#7ce0c5}.dot.power{background:#e5a16f}.dot.wire{background:#ce8eb3}.dot.hardware{background:#d7bd7b}.dot.print{background:#bac7d1}.dot.cad{background:#9db2c5}.dot.proxy{background:#e9bd83}
.bom-foot{display:flex;align-items:center;gap:5px 7px;flex-wrap:wrap;font-size:10px;color:var(--muted);padding:10px 12px}
.instance-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;margin:5px 0 7px;padding:0 5px}
.instance{font-size:10px;text-align:left;padding:4px 5px;min-height:28px;overflow-wrap:anywhere}
.empty{padding:18px 8px;color:var(--muted);font-size:13px}
#dialog{width:min(900px,calc(100% - 24px));max-height:88vh;padding:0;border:1px solid #41607a;border-radius:12px;background:#122131;color:var(--text);overflow:auto}
#dialog::backdrop{background:#040a10cb}
.dialog-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#142335;z-index:2}
.dialog-head h2{font-size:17px}
#dialog-content{padding:15px}
#dialog-content img.full{display:block;width:100%;height:auto;max-height:65vh;object-fit:contain;background:#eef2f4;border-radius:6px}
#dialog-content p,#dialog-content li{font-size:13px;line-height:1.65;margin-bottom:8px}
#dialog-content summary{cursor:pointer;color:var(--blue);font-size:13px;margin:10px 0}
#dialog-content pre{white-space:pre-wrap;font-size:11px}
.pin-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0}
.pin-grid section{padding:10px;border:1px solid var(--line);border-radius:6px}
.pin-grid h3{font-size:13px;color:var(--mint);margin-bottom:4px}
.pin-grid table{border-collapse:collapse;width:100%;font-size:12px}
.pin-grid th,.pin-grid td{text-align:left;padding:4px 3px;border-bottom:1px solid var(--line)}
.pin-grid th{color:var(--muted)}
@media(max-width:1150px){.workspace{grid-template-columns:minmax(152px,175px) minmax(0,1fr) minmax(213px,255px);gap:8px;padding:8px}.step{font-size:12px}}
@media(max-width:875px){.workspace{grid-template-columns:minmax(0,1fr) minmax(210px,270px)}.stages{grid-column:1/-1;position:static}.stages .panel-head{padding-top:9px}.stages nav#steps{display:flex;overflow:auto;padding-top:1px}.step{flex:0 0 auto;width:auto;white-space:nowrap;margin-inline:2px}.bom{top:7px}}
@media(max-width:610px){.mast{padding:10px;align-items:flex-start}.identity{gap:7px}.logo{display:none}h1{font-size:19px}.top-actions{flex-direction:column;align-items:flex-end;gap:3px}.top-actions button{font-size:11px;min-height:26px}.workspace{grid-template-columns:1fr}.bom{position:static}#bom-list{max-height:54vh}#viewport{height:390px}.scene-bar{padding:7px 6px}.scene-bar button{padding:3px 7px}.pin-grid{grid-template-columns:1fr}}
CSS"
````

---

## ChatGPT（2026-11-12 00:59 UTC）

組裝順序已整理成 14 步，包含舵機編號、機構裝配、供電、配線和首次上電。接下來會在瀏覽器實測爆炸、零件點選和步驟切換。

---

## ChatGPT（2026-11-12 01:02 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > viewer.js <<'JS'
'use strict';
const byId = id => document.getElementById(id);
const cats = {print:'列印件', motor:'馬達', electronic:'電子', power:'電源', wire:'線材', hardware:'五金'};
const precision = {cad:'上游 CAD 網格', 'print-placement':'原版列印網格 · 依頭殼座標定位', proxy:'位置或外形示意', route:'配線路徑示意'};
const rowMap = new Map(DATA.bom.map(row => [row.k,row]));
const instances = new Map(DATA.bom.map(row => [row.k,DATA.parts.filter(p => p.k === row.k)]));
const partMap = new Map(DATA.parts.map(p => [p.id,p]));
const state = {step:0, mode:'assembly', amount:0, selection:null, only:false, camera:'iso'};
const progressKey = 'open-duck-mini-v2-assembly-b23317a-progress';
let completed = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(progressKey) || '[]');
  if (Array.isArray(saved)) completed = new Set(saved.filter(i => Number.isInteger(i) && i >= 0 && i < steps.length));
} catch (error) { /* File URLs can have storage disabled. */ }
const htmlEscape = value => String(value).replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[ch]));
const e = htmlEscape;
function isStepPart(part, step=state.step) {
  if (step === 0) return part.k === 'sts';
  const guide = steps[step];
  return part.stage === step || guide.include?.includes(part.id) || guide.includeKeys?.includes(part.k) || false;
}
function selectedParts() {
  return partMap.has(state.selection) ? [partMap.get(state.selection)] : instances.get(state.selection) || [];
}
function selectedRow() {
  return rowMap.get(partMap.get(state.selection)?.k || state.selection);
}
function renderSteps() {
  byId('progress').value = completed.size;
  byId('progress-text').textContent = completed.size+'／'+steps.length+' 步完成';
  byId('steps').innerHTML = steps.map((s,i) => '<button class=\"step\" data-step=\"'+i+'\" aria-current=\"'+(i===state.step?'step':'false')+'\"><span class=\"number\">'+String(i+1).padStart(2,'0')+'</span><span>'+e(s.title)+'</span>'+(completed.has(i)?'<span class=\"done\" aria-label=\"已完成\">✓</span>':'')+'</button>').join('');
}
function renderDetails() {
  const step = steps[state.step];
  const marked = completed.has(state.step);
  const gallery = step.pics.map(([key,label]) => DATA.photos[key] ? '<button class=\"thumb\" data-photo=\"'+e(key)+'\" data-label=\"'+e(label)+'\"><img alt=\"\" src=\"'+DATA.photos[key]+'\"><span>'+e(label)+'</span></button>' : '').join('');
  byId('details').innerHTML = '<h2>'+String(state.step+1).padStart(2,'0')+'　'+e(step.title)+'</h2><p class=\"intro\">'+e(step.summary)+'</p><ol>'+step.tasks.map(t=>'<li>'+e(t)+'</li>').join('')+'</ol><p class=\"checkline\"><strong>驗收</strong>　'+e(step.check)+'</p>'+(gallery?'<div class=\"gallery\" aria-label=\"原版組裝圖\">'+gallery+'</div>':'')+'<p class=\"reference\"><a target=\"_blank\" rel=\"noopener\" href=\"'+e(step.src)+'\">原作者說明 ↗</a><a target=\"_blank\" rel=\"noopener\" href=\"'+e(RUNTIME)+'\">Runtime v2 ↗</a></p><div class=\"step-bottom\"><button id=\"mark\" class=\"complete\" aria-pressed=\"'+marked+'\">'+(marked?'✓ 已完成（點一下取消）':'標記這步已完成')+'</button><div><button id=\"prev\" '+(state.step===0?'disabled':'')+'>上一步</button><button id=\"next\" '+(state.step===steps.length-1?'disabled':'')+'>下一步</button></div></div>';
}
function rowStage(row) {
  const list=instances.get(row.k);
  if(list.length) return list.some(p => isStepPart(p));
  const table={horns:[0,1,2,3,4,5,6,7],screws:[1,2,3,4,5,6,7,10,11],lock:[1,2,3,4,5,6,7],sheath:[9,10,12],controller:[13]};
  return table[row.k]?.includes(state.step) || false;
}
function searchText(row) {
  const ps=instances.get(row.k);
  return [row.name,row.spec,row.note,row.k,cats[row.cat],...ps.flatMap(p=>[p.name,p.zone,p.detail,p.motor && ('ID '+p.motor)])].filter(Boolean).join(' ').toLowerCase();
}
function renderBom() {
  const oldScroll=byId('bom-list').scrollTop;
  const keywords=byId('search').value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
  const filter=byId('category').value;
  const onlyStep=byId('step-only').checked;
  const match=DATA.bom.filter(r => (filter==='all'||r.cat===filter) && ("'!onlyStep||rowStage(r)) && keywords.every(word=>searchText(r).includes(word)));
  const active=selectedRow()?.k;
  byId('"'bom-count').textContent = match.length+'／'+DATA.bom.length+' 類 · 51 件列印件';
  byId('bom-list').innerHTML=match.length?match.map(r=>{
    const list=instances.get(r.k);
    const selected=r.k===active;
    const qty=typeof r.qty==='number'?'×'+r.qty:r.qty;
    const description=r.spec+(r.opt?' · 選配':'');
    const children=selected && list.length>1 ? '<div class=\"instance-list\" aria-label=\"個別安裝位置\">'+list.map(p=>'<button class=\"instance\" data-instance=\"'+e(p.id)+'\" aria-pressed=\"'+(p.id===state.selection)+'\">'+e(p.motor?'ID '+p.motor+' · '+p.name:p.zone+' · '+(p.name===r.name?'位置 '+(list.indexOf(p)+1):p.name))+'</button>').join('')+'</div>' : '';
    return '<button class=\"bom-row\" data-bom=\"'+e(r.k)+'\" aria-pressed=\"'+selected+'\"><span class=\"dot '+r.cat+'\"></span><span><strong>'+e(r.name)+'</strong><small>'+e(description)+'</small></span><span class=\"qty\">'+e(qty)+'</span></button>'+children;
  }).join(''):'<p class=\"empty\">沒有符合條件的零件。</p>';
  byId('bom-list').scrollTop=oldScroll;
}
function renderSelection() {
  const row=selectedRow(), parts=selectedParts(), el=byId('selection');
  if ("'!row) {el.hidden=true;el.innerHTML='"'';return;}
  const picked=partMap.get(state.selection);
  const title=picked ? (picked.motor?'ID '+picked.motor+' · ':'')+picked.name : row.name;
  const caption=picked ? picked.zone+' · '+precision[picked.src] : (parts.length?'3D 中有 '+parts.length+' 個位置或組件':'採購項／外部耗材');
  el.innerHTML='<strong>'+e(title)+'</strong><p>'+e(caption)+'</p><p>'+e(row.spec)+(row.note?' · '+e(row.note):'')+'</p><p><button id=\"clear-pick\">清除選取</button>'+(row.link?' <a href=\"'+e(row.link)+'\" target=\"_blank\" rel=\"noopener\">原資料 ↗</a>':'')+'</p>';
  el.hidden=false;
}
function refreshControls() {
  document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mode===state.mode));
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===state.camera));
  byId('only-focus').setAttribute('aria-pressed',String(state.only));
  byId('spread').value=Math.round(state.amount*100);
  byId('spread-value').value=Math.round(state.amount*100)+'%';
}
function chooseStep(index) {
  if(index<0||index>=steps.length)return;
  state.step=index;state.selection=null;
  if(index===12) byId('wires').checked=true;
  renderSteps();renderDetails();renderBom();renderSelection();
  if (state.only) fit(true);
  requestRender();
}
function choosePart(id, fromCanvas=false) {
  const priorId=state.selection;
  state.selection=priorId===id?null:id;
  const row=selectedRow(), list=selectedParts();
  if(row && list.some(p=>p.cat==='wire')) byId('wires').checked=true;
  if(row && list.some(p=>p.opt)) byId('options').checked=true;
  if(row && list.length && (row.cat"'!=='"'print'||list.some(p=>p.opt)) && state.mode==='assembly'){
    state.mode='cut';
  }
  if (state.only && row && list.length===0) state.only=false;
  renderBom();renderSelection();refreshControls();requestRender();
  if(state.only) fit(true);
  if(fromCanvas && row){
    const b=byId('bom-list').querySelector('[data-bom=\"'+row.k+'\"]');
    if(b) b.scrollIntoView({block:'nearest'});
  }
}
function setMode(mode) {
  state.mode=mode;
  state.amount=mode==='exploded'?(state.amount||.56):0;
  refreshControls();requestRender();fit(true);
}
function showDialog(title,content) {
  byId('dialog-title').textContent=title;
  byId('dialog-content').innerHTML=content;
  const d=byId('dialog');
  if("'!d.open) d.showModal();
  d.scrollTop=0;
}
function showPhoto(key,label) {
  const src=DATA.photos[key];
  if(src) showDialog(label,'"'<img class=\"full\" src=\"'+src+'\" alt=\"'+e(label)+'\"><p>圖源　Open Duck Mini v2／Antoine Pirrone 與貢獻者</p>');
}
function showWiring() {
  const map=pinGroups.map(([title,rows])=>'<section><h3>'+e(title)+'</h3><table><thead><tr><th>訊號</th><th>Pi 實體腳位</th><th>功能</th></tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+e(cell)+'</td>').join('')+'</tr>').join('')+'</tbody></table></section>').join('');
  showDialog('接線圖與 GPIO 腳位','<p>舵機支路使用 2S 原電壓，Pi 使用 UBEC 穩壓 5 V。原作者的接線圖與所用模組的腳位標示優先。</p><img class=\"full\" alt=\"Open Duck Mini v2 系統接線圖\" src=\"'+DATA.photos['system-wiring']+'\"><div class=\"pin-grid\">'+map+'</div><p><a href=\"'+UP+'assembly_guide.md#electronics\" target=\"_blank\" rel=\"noopener\">原作者接線與腳位 ↗</a></p>');
}
function showSources() {
  showDialog('來源與模型精度','<ul><li><strong>原版網格</strong>　列印結構與 14 顆 STS3215 使用上游 CAD／MJCF。51 件列印件中有 7 件表情相關印件以原版 STL 的頭殼座標合併顯示。標準姿勢沿用原模型零位。</li><li><strong>位置或外形示意</strong>　部分 PCB、天線舵機、microSD、排針、足底開關、接頭、選配電子、緊固件與線束。請用原作者照片、接線圖及實物確認孔位、方向與線長。</li><li><strong>BOM 數量</strong>　以原 BOM 與列印指南為準。供應商變體、安裝零件的尺寸、公差和逐孔螺絲清單需依實物確認。用料與工具保留在 BOM 供查找。</li><li><strong>爆炸距離</strong>　供辨識與點選，滑桿不表示實際拆裝路徑或間隙。</li><li><strong>離線使用</strong>　模型和照片已內嵌。組裝進度存於瀏覽器，若瀏覽器限制本機檔案儲存，進度只保留在當次開啟。</li></ul><p><a href=\"'+REPO+'/tree/'+DATA.commit+'\" target=\"_blank\" rel=\"noopener\">固定上游版本 ↗</a> · <a href=\"'+UP+'print_guide.md\" target=\"_blank\" rel=\"noopener\">原列印清單 ↗</a> · <a href=\"'+BOM_URL+'\" target=\"_blank\" rel=\"noopener\">原 BOM ↗</a></p><details><summary>模型及程式授權</summary><pre>'+e(LICENSES)+'</pre></details>');
}

byId('steps').addEventListener('click',event=>{
 const b=event.target.closest('[data-step]');
 if(b) chooseStep(Number(b.dataset.step));
});
byId('details').addEventListener('click',event=>{
 const b=event.target.closest('button');if("'!b)return;
 if(b.id==='"'prev') chooseStep(state.step-1);
 else if(b.id==='next') chooseStep(state.step+1);
 else if(b.dataset.photo) showPhoto(b.dataset.photo,b.dataset.label);
 else if(b.id==='mark'){
   if(completed.has(state.step)) completed.delete(state.step); else completed.add(state.step);
   try{localStorage.setItem(progressKey,JSON.stringify([...completed]));}catch(error){/* Optional persistence. */}
   renderSteps();renderDetails();
 }
});
byId('bom-list').addEventListener('click',event=>{
 const b=event.target.closest('button');if(b) choosePart(b.dataset.instance||b.dataset.bom);
});
byId('selection').addEventListener('click',event=>{if(event.target.id==='clear-pick') choosePart(state.selection);});
byId('search').addEventListener('input',renderBom);
byId('category').addEventListener('change',renderBom);
byId('step-only').addEventListener('change',renderBom);
byId('wire-guide').addEventListener('click',showWiring);
byId('sources').addEventListener('click',showSources);
byId('close-dialog').addEventListener('click',()=>byId('dialog').close());
byId('dialog').addEventListener('click',event=>{if(event.target===byId('dialog')) byId('dialog').close();});
byId('spread').addEventListener('input',event=>{
 state.amount=Number(event.target.value)/100;
 if(state.amount>0) state.mode='exploded';
 refreshControls();requestRender();
});
byId('wires').addEventListener('change',requestRender);
byId('options').addEventListener('change',requestRender);
document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
byId('only-focus').addEventListener('click',()=>{
 const row=selectedRow();
 if(row && "'!selectedParts().length) choosePart(state.selection);
 state.only=!state.only;
 refreshControls();fit(true);
});
byId('"'fit').addEventListener('click',()=>fit(true));
renderSteps();renderDetails();renderBom();refreshControls();

let viewport, renderer, camera, scene, rig;
let ready=false, pending=false;
let spherical, target, raycaster, mouse;
const objects=[], geometryCache=new Map(), primitiveCache=new Map();
const stageMaterial=new Map(), scratchMaterials=new Map(), poses={iso:[.65,1.35],front:[0,1.54],back:[Math.PI,1.54],side:[Math.PI/2,1.54]};
function bytes(encoded) {
 const raw=atob(encoded);
 const result=new Uint8Array(raw.length);
 for(let i=0;i<raw.length;i++) result[i]=raw.charCodeAt(i);
 return result;
}
function decodeGeometry(key) {
 if(geometryCache.has(key)) return geometryCache.get(key);
 const [nv,ni,width,packed]=DATA.geometry[key];
 const data=fflate.gunzipSync(bytes(packed));
 const coordinates=new Int16Array(data.buffer,data.byteOffset,nv*3);
 const vertices=new Float32Array(nv*3);
 for(let i=0;i<vertices.length;i++)vertices[i]=coordinates[i]/100;
 const rawIndices=new DataView(data.buffer,data.byteOffset+nv*6,ni*width);
 const index=width===2?new Uint16Array(ni):new Uint32Array(ni);
 for(let i=0;i<ni;i++) index[i]=width===2?rawIndices.getUint16(i*2,true):rawIndices.getUint32(i*4,true);
 const geometry=new THREE.BufferGeometry();
 geometry.setAttribute('position',new THREE.BufferAttribute(vertices,3));
 geometry.setIndex(new THREE.BufferAttribute(index,1));
 geometry.computeBoundingBox();
 geometry.computeBoundingSphere();
 geometryCache.set(key,geometry);
 return geometry;
}
function primitive(shape) {
 const key=JSON.stringify(shape.box||shape.cyl||shape.ring);
 if(primitiveCache.has(key)) return primitiveCache.get(key);
 let g;
 if(shape.box) g=new THREE.BoxGeometry(...shape.box);
 else if(shape.cyl){
   const [radius,length,axis]=shape.cyl;
   g=new THREE.CylinderGeometry(radius,radius,length,18);
   if(axis==='x') g.rotateZ(-Math.PI/2); else if(axis==='z') g.rotateX(Math.PI/2);
 } else {
   const [outer,inner,h]=shape.ring;
   const s=new THREE.Shape();s.absarc(0,0,outer,0,2*Math.PI,false);
   const hole=new THREE.Path();hole.absarc(0,0,inner,0,2*Math.PI,true);
   s.holes.push(hole);
   g=new THREE.ExtrudeGeometry(s,{depth:h,steps:1,bevelEnabled:false,curveSegments:12});
   g.translate(0,0,-h/2);g.rotateX(Math.PI/2);
 }
 g.computeBoundingBox();
 primitiveCache.set(key,g);
 return g;
}
function material(color,variant) {
 const cacheKey=color+'|'+variant;
 if(stageMaterial.has(cacheKey)) return stageMaterial.get(cacheKey);
 const tint=new THREE.Color(color);
 const targetColor=variant==='selected'?new THREE.Color('#88f3d2'):
   variant==='active'?tint.clone().lerp(new THREE.Color('#76c9c7'),.31):
   variant==='dim'?tint.clone().lerp(new THREE.Color('#203143'),.63):tint;
 const translucent=variant==='ghost';
 const m=new THREE.MeshStandardMaterial({color:targetColor,flatShading:true,roughness:.73,
   metalness:0.04,side:THREE.DoubleSide,transparent:translucent,opacity:translucent?.13:1,depthWrite:"'!translucent});
 if(variant==='"'selected'){m.emissive.set('#4aa385');m.emissiveIntensity=.37;}
 if(translucent){m.color.lerp(new THREE.Color('#9aafd0'),.45);}
 stageMaterial.set(cacheKey,m);
 return m;
}
function makePart(part,index) {
 const group=new THREE.Group();
 group.userData.part=part;
 const center=new THREE.Vector3(...part.c);
 for(const s of part.sh){
   let geometry, relative;
   if(s.tube){
     const curve=new THREE.CatmullRomCurve3(s.tube.map(p=>new THREE.Vector3(...p).sub(center)));
     geometry=new THREE.TubeGeometry(curve,Math.max(9,s.tube.length*5),1.45,7,false);
     geometry.computeBoundingBox();
     relative=new THREE.Vector3();
   } else {
     geometry=s.m?decodeGeometry(s.m):primitive(s);
     relative=new THREE.Vector3(...s.p).sub(center);
   }
   const color=s.color||part.color;
   const mesh=new THREE.Mesh(geometry,material(color,'base'));
   mesh.userData.part=part;mesh.userData.color=color;
   mesh.position.copy(relative);
   if(s.q) mesh.quaternion.fromArray(s.q);
   group.add(mesh);
 }
 group.position.copy(center);
 rig.add(group);
 const delta=explosion(part,index);
 return {part,group,center,delta};
}
function explosion(part,index) {
 const [x,y,z]=part.c;
 const side=Math.abs(x)>8?Math.sign(x):(index%2?1:-1);
 const signZ=Math.abs(z)>9?Math.sign(z):(index%3?1:-1);
 const bump=(index%7-3)*9;
 const strength=part.cover?1.25:1;
 if(part.cat==='wire')return new THREE.Vector3(0,0,0);
 if(part.stage===9)return new THREE.Vector3(x*.84+side*(24+Math.abs(bump)),(y-236)*.55+bump*.7,-100-(index%5)*13);
 if(part.stage===2)return new THREE.Vector3(side*(45+Math.abs(bump)),-23+(y-13)*1.36+bump*.53,z*.55+signZ*(24+Math.abs(bump)));
 if(part.stage>=3 && part.stage<=5)return new THREE.Vector3(side*(47+Math.abs(bump)+Math.abs(x)*.51),(y-188)*.52+bump,z*.53+signZ*(31+Math.abs(bump)));
 if(part.stage>=6 && part.stage<=7 || y>320)return new THREE.Vector3((x*.80+side*(24+Math.abs(bump)))*strength,(y-286)*.62+bump+38,(z*.72+signZ*(27+Math.abs(bump)))*strength);
 return new THREE.Vector3((x*.75+side*(25+Math.abs(bump)))*strength,(y-205)*.6+bump,(z*.72+signZ*(26+Math.abs(bump)))*strength);
}
function updateScene() {
 if("'!ready) return;
 const selected=new Set(selectedParts().map(p=>p.id));
 const hasSelection=selected.size>0;
 const stepOnly=state.only&&!hasSelection;
 const allowOptional=byId('"'options').checked;
 const allowWires=byId('wires').checked;
 for(const {part,group,center,delta} of objects){
   const inStep=isStepPart(part);
   const hit=selected.has(part.id);
   group.visible=(allowOptional||"'!part.opt||hit) && (allowWires||part.cat!=='"'wire'||hit) &&
     ("'!state.only||(hasSelection?hit:inStep));
   group.position.copy(center).addScaledVector(delta,state.amount);
   if(!group.visible)continue;
   const ghost=state.mode==='"'cut'&&part.cover&&"'!hit;
   const variant=hit?'"'selected':ghost?'ghost':hasSelection?'dim':state.only||state.step>0?(inStep?'active':'base'):'base';
   for(const m of group.children){
     m.material=material(m.userData.color,variant);
     m.renderOrder=ghost?4:0;
   }
 }
}
function cameraUpdate() {
 const offset=new THREE.Vector3().setFromSpherical(spherical);
 camera.position.copy(target).add(offset);
 camera.lookAt(target);
}
function requestRender() {
 if("'!ready||pending)return;
 pending=true;
 requestAnimationFrame(()=>{
   pending=false;
   updateScene();cameraUpdate();renderer.render(scene,camera);
 });
}
function fit(moveTarget) {
 if(!ready)return;
 updateScene();
 const box=new THREE.Box3();
 for(const {group} of objects){
   if(!group.visible)continue;
   if(group.userData.part.cat==='"'wire'&&"'!state.only)continue;
   box.expandByObject(group);
 }
 if(box.isEmpty())return;
 if(moveTarget)box.getCenter(target);
 const size=box.getSize(new THREE.Vector3());
 const perspective=THREE.MathUtils.degToRad(camera.fov/2);
 const depth=size.z*.39;
 const vertical=size.y*.57/Math.tan(perspective);
 const horizontal=(size.x*.6+size.z*.18)/(Math.tan(perspective)*camera.aspect);
 spherical.radius=Math.max(43,(Math.max(vertical,horizontal)+depth)*1.06);
 requestRender();
}
function setView(view) {
 state.camera=view;
 if(!ready){refreshControls();return;}
 [spherical.theta,spherical.phi]=poses[view];
 refreshControls();fit(true);
}
function resize() {
 if(!ready)return;
 const width=viewport.clientWidth,height=viewport.clientHeight;
 if(!width||!height)return;
 renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
 requestRender();
}
function selectFromCanvas(event) {
 const rect=renderer.domElement.getBoundingClientRect();
 mouse.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
 scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
 raycaster.setFromCamera(mouse,camera);
 const candidates=objects.filter(o=>o.group.visible).flatMap(o=>o.group.children)
   .filter(m=>m.material.opacity>.2);
 const found=raycaster.intersectObjects(candidates,false)[0];
 if(found)choosePart(found.object.userData.part.id,true);
 else if(state.selection)choosePart(state.selection);
}
function cameraGestures(canvas) {
 const points=new Map();
 let moved=false, pinch=null;
 canvas.addEventListener('"'contextmenu',event=>event.preventDefault());
 canvas.addEventListener('pointerdown',event=>{
   canvas.setPointerCapture(event.pointerId);
   points.set(event.pointerId,{x:event.clientX,y:event.clientY,button:event.button});
   if(points.size===1){moved=false;pinch=null;}
   if(points.size===2){moved=true;pinch=distance();}
 });
 function distance() {
   const [a,b]=points.values();
   return Math.hypot(a.x-b.x,a.y-b.y);
 }
 canvas.addEventListener('pointermove',event=>{
   const prev=points.get(event.pointerId);
   if("'!prev)return;
   const dx=event.clientX-prev.x,dy=event.clientY-prev.y;
   if(Math.abs(dx)+Math.abs(dy)>2)moved=true;
   points.set(event.pointerId,{x:event.clientX,y:event.clientY,button:prev.button});
   if(points.size>=2){
     const d=distance();
     if(pinch&&d>5)spherical.radius=THREE.MathUtils.clamp(spherical.radius*pinch/d,25,3200);
     pinch=d;
   } else if(prev.button===2||prev.button===1||event.shiftKey){
     const scale=spherical.radius/viewport.clientHeight*.68;
     const right=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0);
     const up=new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1);
     target.addScaledVector(right,-dx*scale).addScaledVector(up,dy*scale);
   } else {
     spherical.theta-=dx*.008;
     spherical.phi=THREE.MathUtils.clamp(spherical.phi-dy*.008,.07,Math.PI-.07);
   }
   requestRender();
 });
 canvas.addEventListener('"'pointerup',event=>{
   if(points.size===1&&"'!moved&&event.button===0)selectFromCanvas(event);
   points.delete(event.pointerId);pinch=null;
 });
 canvas.addEventListener('"'pointercancel',event=>{points.delete(event.pointerId);pinch=null;});
 canvas.addEventListener('wheel',event=>{
   event.preventDefault();
   spherical.radius=THREE.MathUtils.clamp(spherical.radius*Math.exp(event.deltaY*.001),25,3200);
   requestRender();
 },{passive:false});
 canvas.addEventListener('keydown',event=>{
   if(event.key==='Escape'){if(state.selection)choosePart(state.selection);return;}
   if(event.key==='ArrowLeft')spherical.theta-=.1;
   else if(event.key==='ArrowRight')spherical.theta+=.1;
   else if(event.key==='ArrowUp')spherical.phi=Math.max(.07,spherical.phi-.1);
   else if(event.key==='ArrowDown')spherical.phi=Math.min(Math.PI-.07,spherical.phi+.1);
   else if(event.key==='+'||event.key==='=')spherical.radius=Math.max(25,spherical.radius*.9);
   else if(event.key==='-')spherical.radius=Math.min(3200,spherical.radius*1.1);
   else return;
   event.preventDefault();requestRender();
 });
}
function boot() {
 try {
   viewport=byId('viewport');
   renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'high-performance'});
   renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.8));
   renderer.setClearColor(0,0);
   renderer.outputColorSpace=THREE.SRGBColorSpace;
   renderer.toneMapping=THREE.ACESFilmicToneMapping;
   renderer.toneMappingExposure=1.28;
   const canvas=renderer.domElement;
   canvas.tabIndex=0;canvas.setAttribute('aria-label','互動 3D 模型。方向鍵旋轉，加減鍵縮放。');
   viewport.prepend(canvas);
   scene=new THREE.Scene();
   camera=new THREE.PerspectiveCamera(35,1,.5,5000);
   target=new THREE.Vector3(0,220,0);
   spherical=new THREE.Spherical(860,poses.iso[1],poses.iso[0]);
   raycaster=new THREE.Raycaster();mouse=new THREE.Vector2();
   rig=new THREE.Group();scene.add(rig);
   scene.add(new THREE.HemisphereLight('#e7f1ff','#6f8193',2.05));
   const key=new THREE.DirectionalLight('#fff1de',2.1);key.position.set(180,400,330);scene.add(key);
   const rim=new THREE.DirectionalLight('#8ab5e8',1.6);rim.position.set(-280,270,-250);scene.add(rim);
   const grid=new THREE.GridHelper(900,36,0x42617b,0x294156);grid.position.y=-2;scene.add(grid);
   DATA.parts.forEach((part,i)=>objects.push(makePart(part,i)));
   ready=true;
   resize();fit(true);cameraGestures(canvas);
   new ResizeObserver(resize).observe(viewport);
   byId('scene-status').hidden=true;
   canvas.addEventListener('webglcontextlost',event=>{
     event.preventDefault();ready=false;byId('scene-status').hidden=false;
     byId('scene-status').textContent='3D 圖形連線已中斷。重新開啟檔案可再載入模型。';
   });
   document.documentElement.dataset.ready='true';
 } catch(error){
   console.error(error);
   byId('scene-status').textContent='這個瀏覽器目前無法繪製 3D 模型。BOM、組裝步驟和接線圖仍可使用。';
   document.documentElement.dataset.ready='false';
 }
}
requestAnimationFrame(boot);
JS
sed -i 's/, scratchMaterials=new Map()//' viewer.js
python build.py
node --check viewer.js
node --check guide.js
ls -lh /mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html"
````

---

## ChatGPT（2026-11-12 01:03 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > verify.py <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from collections import Counter
url=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html').as_uri()
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
 ctx=browser.new_context(viewport={'width':1440,'height':960}, offline=True)
 page=ctx.new_page()
 errors=[]
 remote=[]
 page.on('pageerror',lambda error: errors.append(str(error)))
 page.on('request',lambda request: remote.append(request.url) if request.url.startswith('http') else None)
 page.on('console',lambda message: print('console',message.text[:400],flush=True) if message.type=='error' else None)
 page.goto(url,wait_until='load',timeout=25000)
 page.wait_for_function(\"document.documentElement.dataset.ready "'!== undefined",timeout=18000)
 assert page.locator('"'html').get_attribute('data-ready')=='true',page.locator('#scene-status').inner_text()
 stats=page.evaluate('''() => ({
   objects:objects.length, selectedMotors: DATA.parts.filter(p=>p.motor).map(p=>p.motor).sort((a,b)=>a-b),
   printQty: DATA.parts.filter(p=>p.cat==='print').length,
   distinctSTL: DATA.bom.filter(p=>p.cat==='print').length,
   steps:steps.length, photos:Object.keys(DATA.photos).length,
   triangles: renderer.info.render.triangles
 })''')
 print('STATS',stats,flush=True)
 assert stats['selectedMotors']==[10,11,12,13,14,20,21,22,23,24,30,31,32,33]
 assert stats['printQty']==51 and stats['distinctSTL']==36 and stats['steps']==14
 page.screenshot(path='assembled-desktop.png')
 page.get_by_role('button',name='爆炸',exact=True).click()
 expect(page.locator('#spread-value')).to_have_text('56%')
 assert page.evaluate('''() => objects.filter(o=>o.group.position.distanceTo(o.center)>3).length>100''')
 page.screenshot(path='exploded-desktop.png')
 page.locator('#search').fill('ID 24')
 expect(page.locator('#bom-list .bom-row')).to_have_count(1)
 page.locator('[data-bom=\"sts\"]').click()
 expect(page.locator('.instance')).to_have_count(14)
 page.locator('[data-instance=\"servo-24\"]').click()
 expect(page.locator('#selection strong')).to_have_text('ID 24 · 左腳踝舵機')
 page.locator('#only-focus').click()
 assert page.evaluate('''() => objects.filter(o=>o.group.visible).map(o=>o.part.id).join(',')==='servo-24' ''')
 page.screenshot(path='isolate-desktop.png')
 page.locator('#only-focus').click()
 page.locator('#search').fill('')
 page.locator('[data-step=\"9\"]').click()
 expect(page.locator('#details h2')).to_contain_text('2S 電池艙')
 page.locator('#step-only').check()
 assert page.locator('.bom-row').count()>6
 page.locator('#mark').click()
 expect(page.locator('#progress-text')).to_contain_text('1／14')
 page.locator('#wire-guide').click()
 expect(page.locator('#dialog')).to_be_visible()
 expect(page.locator('.pin-grid')).to_contain_text('GPIO 27')
 page.keyboard.press('Escape')
 expect(page.locator('#dialog')).not_to_be_visible()
 page.locator('#details .thumb').first.click()
 expect(page.locator('#dialog img')).to_be_visible()
 assert page.locator('#dialog img').evaluate('(i)=>i.complete && i.naturalWidth>0')
 page.keyboard.press('Escape')
 page.locator('#sources').click()
 expect(page.locator('#dialog')).to_contain_text('位置或外形示意')
 page.keyboard.press('Escape')
 page.locator('[data-step=\"12\"]').click()
 assert page.locator('#wires').is_checked()
 page.reload(wait_until='load')
 expect(page.locator('#progress-text')).to_contain_text('1／14')
 assert not errors, errors
 assert not remote, remote
 phone=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True,offline=True)
 phone.goto(url,wait_until='load',timeout=25000)
 phone.wait_for_function(\"document.documentElement.dataset.ready === 'true'\",timeout=16000)
 assert phone.evaluate('document.documentElement.scrollWidth')==390
 phone.screenshot(path='mobile.png')
 print('Offline, 3D modes, servo instance selection, isolation, step filter, GPIO, photos, progress reload and mobile passed.',flush=True)
 browser.close()
PY
python verify.py"
````

---

## ChatGPT（2026-11-12 01:03 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
printf 'Browser executables\\n'
find /opt /ms-playwright /usr/lib /home/agent/.cache -maxdepth 8 \\( -name chrome-headless-shell -o -name headless_shell -o -name firefox \\) -type f 2>/dev/null | head -30
printf '\\nSocket test\\n'
python - <<'PY'
import socket
for family in [socket.AF_UNIX,socket.AF_INET]:
 try: s=socket.socket(family); print(family,'ok')
 except OSError as e: print(family,e)
from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)
PY
printf '\\nInstalled UI tool\\n'
ls /usr/lib/chromium | head -18"
````

---

## ChatGPT（2026-11-12 01:03 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'cd /tmp/duck-viewer
python -m playwright install --only-shell chromium'
````

---

## ChatGPT（2026-11-12 01:03 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "ls -la /home/agent/.cache/ms-playwright
ls /opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules | rg 'jsdom|linkedom|canvas|puppet|playwright|esbuild'"
````

---

## ChatGPT（2026-11-12 01:04 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
apt-cache policy chromium-headless-shell
apt-cache show chromium-headless-shell | rg -m 5 '"'^(Version|Filename|Size):'"'
curl -sSI --max-time 8 https://storage.googleapis.com/chrome-for-testing-public/143.0.7499.192/linux64/chrome-headless-shell-linux64.zip | head -14
df -h /tmp"
````

---

## ChatGPT（2026-11-12 01:04 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-12 01:04 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-12 01:05 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > verify_node.cjs <<'JS'
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class FakeElement {
  constructor(id='') {
    this.id=id;
    this.value='';
    this.checked=id==='options';
    this.dataset={};
    this.hidden=false;
    this.open=false;
    this.scrollTop=0;
    this.clientWidth=870;
    this.clientHeight=520;
    this.listeners={};
    this.attributes={};
  }
  setAttribute(k,v){ this.attributes[k]=String(v); }
  addEventListener(n,f){ this.listeners[n]=f; }
  click(extra={}){ this.listeners.click?.({target:this,...extra}); }
  closest(){ return this; }
  prepend(){ }
  showModal(){ this.open=true; }
  close(){ this.open=false; }
  querySelector(){ return null; }
  getBoundingClientRect(){ return {left:0,top:0,width:870,height:520}; }
}
const els=new Map();
const get=id=>{if("'!els.has(id))els.set(id,new FakeElement(id));return els.get(id);};
get('"'category').value='all';
const modeButtons=['assembly','exploded','cut'].map(mode=>Object.assign(new FakeElement(),{dataset:{mode}}));
const viewButtons=['iso','front','back','side'].map(view=>Object.assign(new FakeElement(),{dataset:{view}}));
const document={
  getElementById:get, documentElement:{dataset:{}},
  querySelectorAll: q=>q==='[data-mode]'?modeButtons:viewButtons,
};
const saved={};
const queued=[];
class FakeRenderer {
  constructor(){ this.domElement=new FakeElement('canvas');this.frames=0; }
  setPixelRatio(){} setClearColor(){} setSize(){}
  render(scene,camera){scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);this.frames++;}
}
const context=vm.createContext({console:{...console,warn:()=>{}}, document,window:{devicePixelRatio:1},
  TextDecoder, TextEncoder, atob, btoa, Uint8Array, Float32Array, Int16Array, Uint16Array, Uint32Array, DataView, ArrayBuffer,
  localStorage:{getItem:key=>saved[key]??null,setItem:(k,v)=>{saved[k]=v;}},
  requestAnimationFrame:callback=>queued.push(callback), ResizeObserver:class{observe(){}}, FakeRenderer,
});
const html=fs.readFileSync('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html','utf8');
const scripts=[...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)];
assert.equal(scripts.length,5);
assert.equal((html.match(/<(?:script|link|img)["'^>]+(?:src|href)="https?:/g)||[]).length,0);
for (const [i,[,source]] of scripts.entries()) {
  vm.runInContext(source,context,{filename:'"'embedded-'+i+'.js',timeout:18000});
  if(i===0)vm.runInContext('THREE.WebGLRenderer=FakeRenderer',context);
}
function frames(){while(queued.length)queued.shift()();}
function app(expr){return vm.runInContext(expr,context);}
frames();
assert.equal(document.documentElement.dataset.ready,'true');
assert.equal(app('objects.length'),131);
assert.equal(app('DATA.parts.filter(p=>p.cat===\"print\").length'),51);
assert.equal(app('DATA.bom.filter(p=>p.cat===\"print\").length'),36);
assert.equal(app('DATA.parts.filter(p=>p.motor).map(p=>p.motor).sort((a,b)=>a-b).join(\",\")'),'10,11,12,13,14,20,21,22,23,24,30,31,32,33');
assert(app('renderer.frames')>0);
assert.equal(app('geometryCache.size'),52);
assert(app('objects.every(o=>o.group.children.length>0 && o.center.toArray().every(Number.isFinite))'));
assert(app('objects.flatMap(o=>o.group.children).every(m=>m.geometry.boundingBox"'!==null)'"'));
const extent=app('new THREE.Box3().setFromObject(rig).getSize(new THREE.Vector3()).toArray().map(x=>Math.round(x)).join(\",\")');
console.log('CAD pose envelope (mm)',extent);
modeButtons[1].click();frames();
assert.equal(get('spread-value').value,'56%');
assert(app('objects.filter(o=>o.group.position.distanceTo(o.center)>3).length')>110);
get('search').value='ID 24';get('search').listeners.input();
assert.equal((get('bom-list').innerHTML.match(/data-bom=/g)||[]).length,1);
app('choosePart(\"sts\")');frames();
assert.equal((get('bom-list').innerHTML.match(/data-instance=/g)||[]).length,14);
app('choosePart(\"servo-24\")');frames();
assert(get('selection').innerHTML.includes('ID 24 · 左腳踝舵機'));
get('only-focus').click();frames();
assert.equal(app('objects.filter(o=>o.group.visible).map(o=>o.part.id).join(\",\")'),'servo-24');
assert(app('camera.position.toArray().every(Number.isFinite)'));
get('only-focus').click();frames();
get('search').value='';get('search').listeners.input();
app('chooseStep(9)');frames();
assert(get('details').innerHTML.includes('2S 電池艙與供電'));
get('step-only').checked=true;get('step-only').listeners.change();
assert(get('bom-list').innerHTML.includes('data-bom=\"ubec\"'));
get('details').listeners.click({target:new FakeElement('mark')});
assert(get('progress-text').textContent.includes('1／14'));
assert.equal(Object.values(saved)[0],'[9]');
get('wire-guide').click();
assert(get('dialog').open && get('dialog-content').innerHTML.includes('GPIO 27'));
get('close-dialog').click();
assert("'!get('"'dialog').open);
app('showPhoto(\"assembled\",\"驗證圖片\")');
assert(get('dialog-content').innerHTML.includes('data:image/jpeg;base64,'));
app('chooseStep(12)');frames();
assert(get('wires').checked);
assert(app('objects.filter(o=>o.part.cat===\"wire\"&&o.group.visible).length')>=10);
app('chooseStep(13)');frames();
assert(get('details').innerHTML.includes('首次動作測試'));
console.log('Offline embedding, decoded geometries, IDs, assembly state, explosion, filters, isolation, photos, pin tables and saved progress passed. WebGL draw is stubbed.');
JS
node verify_node.cjs"
````

---

## ChatGPT（2026-11-12 01:05 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc 'command -v blender || true
ls -lh /mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html
du -sh /tmp/duck-viewer
ls -l /home/agent/.codex/plugins/cache/openai-curated-remote/openai-library/0.1.69/skills/library/scripts/library_file_transfer.py'
````

---

## ChatGPT（2026-11-12 01:05 UTC）

模型資料和操作邏輯已通過檢查，包括 51 件列印件、14 顆主舵機的 ID、BOM 篩選和進度記錄。目前的測試瀏覽器擋住了本機檔案，我會另外檢查組裝模型的外觀，並加上靜態預覽。

---

## ChatGPT（2026-11-12 01:06 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
cat > render_overview.py <<'PY'
from pathlib import Path
import bpy
import json
import gzip
import base64
from mathutils import Quaternion, Vector
from array import array

html=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html').read_text()
i=html.index('const DATA=')+len('const DATA=')
data=json.JSONDecoder().raw_decode(html,i)[0]
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
mats={}
def material(hexcol):
 if hexcol not in mats:
  c=[int(hexcol[i:i+2],16)/255 for i in (1,3,5)]
  rgb=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in c]
  mat=bpy.data.materials.new(hexcol)
  mat.diffuse_color=(*rgb,1)
  mats[hexcol]=mat
 return mats[hexcol]
cache={}
def geometry(key,color):
 token=[REDACTED_SECRET]
 if token not in cache:
  nv,ni,width,compressed=data['geometry'][key]
  raw=gzip.decompress(base64.b64decode(compressed))
  v=array('h');v.frombytes(raw[:nv*6])
  indices=array('H' if width==2 else 'I');indices.frombytes(raw[nv*6:])
  pts=[tuple(c*.00001 for c in v[i:i+3]) for i in range(0,len(v),3)]
  faces=[tuple(indices[i:i+3]) for i in range(0,len(indices),3)]
  mesh=bpy.data.meshes.new(key)
  mesh.from_pydata(pts,[],faces)
  mesh.update()
  mesh.materials.append(material(color))
  cache[token]=mesh
 return cache[token]
for item in data['parts']:
 if item['cat']=='wire':continue
 for s in item['sh']:
  if 'm' not in s:continue
  mesh=geometry(s['m'],s.get('color',item['color']))
  obj=bpy.data.objects.new(item['name'],mesh)
  scene.collection.objects.link(obj)
  x,y,z=s['p']
  obj.location=(x*.001,-z*.001,y*.001)
  rx,ry,rz,rw=s['q']
  adjust=Quaternion((1,0,0),1.57079632679)
  obj.rotation_mode='QUATERNION'
  obj.rotation_quaternion=adjust@Quaternion((rw,rx,ry,rz))
bpy.ops.mesh.primitive_plane_add(size=4,location=(0,0,-.002))
bpy.context.object.data.materials.append(material('#172739'))
camdat=bpy.data.cameras.new('Overview')
cam=bpy.data.objects.new('Overview',camdat)
scene.collection.objects.link(cam)
cam.location=(.55,-.85,.48)
target=Vector((0,0,.254))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
camdat.type='ORTHO'
camdat.ortho_scale=.66
scene.camera=cam
def light(name,loc,power,diameter,tint):
 dat=bpy.data.lights.new(name,'AREA');dat.energy=power;dat.shape='DISK';dat.size=diameter;dat.color=tint
 ob=bpy.data.objects.new(name,dat);scene.collection.objects.link(ob);ob.location=loc
 ob.rotation_euler=(target-ob.location).to_track_quat('-Z','Y').to_euler()
light('Key',(.45,-.45,.84),80,.6,(1,.92,.83))
light('Fill',(-.62,-.35,.6),48,.7,(.68,.84,1))
light('Rim',(.1,.58,.75),100,.45,(.70,.85,1))
scene.world=bpy.data.worlds.new('Backdrop')
scene.world.color=(.16,.18,.22)
scene.render.engine='CYCLES'
scene.cycles.device='CPU';scene.cycles.samples=8
scene.render.threads_mode='FIXED';scene.render.threads=4
scene.render.resolution_x=710;scene.render.resolution_y=640;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='JPEG';scene.render.image_settings.quality=88
scene.render.filepath='/tmp/duck-viewer/photos/overview.jpg'
bpy.ops.render.render(write_still=True)
PY
blender -b -t 4 --python render_overview.py"
````

---

## ChatGPT（2026-11-12 01:06 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
python - <<'PY'
from pathlib import Path
p=Path('index.template')
s=p.read_text().replace('<div id=\"scene-status\" role=\"status\">','<img id=\"static-overview\" alt=\"Open Duck Mini v2 原版 CAD 組裝外觀\" hidden>\\n      <div id=\"scene-status\" role=\"status\">')
p.write_text(s)
p=Path('viewer.js')
s=p.read_text()
a='function boot() {'
b='''function showStaticOverview(message) {
 const status=byId('scene-status'), img=byId('static-overview');
 status.textContent=message;
 status.hidden=false;
 if(DATA.photos.overview){
   img.src=DATA.photos.overview;
   img.hidden=false;
   viewport.classList.add('fallback');
 }
}
function boot() {'''
assert a in s
s=s.replace(a,b)
s=s.replace(\"event.preventDefault();ready=false;byId('scene-status').hidden=false;\\n     byId('scene-status').textContent='3D 圖形連線已中斷。重新開啟檔案可再載入模型。';\",\"event.preventDefault();ready=false;\\n     showStaticOverview('3D 圖形連線已中斷，重新開啟檔案可再載入模型。');\")
s=s.replace(\"byId('scene-status').textContent='這個瀏覽器目前無法繪製 3D 模型。BOM、組裝步驟和接線圖仍可使用。';\",\"showStaticOverview('這個瀏覽器目前無法繪製 3D 模型。BOM、組裝步驟和接線圖仍可使用。');\")
p.write_text(s)
p=Path('viewer.css')
s=p.read_text()+'''
#static-overview{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
#viewport.fallback #scene-status{inset:auto 10px 8px;background:#102033ec;padding:7px 9px;border-radius:6px}
#viewport.fallback .gestures,#viewport.fallback .view-buttons{display:none}
#viewport.fallback #selection{bottom:47px}
'''
p.write_text(s)
PY
node --check viewer.js
ls -l photos/overview.jpg"
````

---

## ChatGPT（2026-11-12 01:06 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "cd /tmp/duck-viewer
sed -i '/scene.cycles.device=/a scene.cycles.use_denoising=False' render_overview.py
blender -b -t 4 --python render_overview.py > overview-render.log 2>&1
tail -7 overview-render.log
test -s photos/overview.jpg"
````

---

## ChatGPT（2026-11-12 01:06 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "set -euo pipefail
cd /tmp/duck-viewer
sed -i 's/primitive_plane_add(size=4,/primitive_plane_add(size=40,/; s/scene.cycles.samples=8/scene.cycles.samples=20/' render_overview.py
blender -b -t 4 --python render_overview.py > overview-render.log 2>&1
test -s photos/overview.jpg
python build.py
node verify_node.cjs
python - <<'PY'
from pathlib import Path
p=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html')
html=p.read_text()
assert '{{DATA}}' not in html and 'const DATA=' in html
assert '\"overview\":\"data:image/jpeg;base64,' in html
assert len(html.encode())==p.stat().st_size
print('Standalone UTF-8 HTML verified.')
PY"
````

---

## ChatGPT（2026-11-12 01:07 UTC）

The output of this plugin was redacted.

---

## ChatGPT（2026-11-12 01:07 UTC）

（程式碼，送往 `container.exec`）

````
bash -lc /bin/bash -lc "python3 '/home/agent/.codex/plugins/cache/openai-curated-remote/openai-library/0.1.69/skills/library/scripts/library_file_transfer.py' apply-xattrs '/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html' 'libfile_1a037f41eeec819184ab891ccb977c0d' <<'LIBRARY_XATTRS'
[{\"name\":\"user.library-file-version\",\"value\":\"0\"}]
LIBRARY_XATTRS"
````

---

## ChatGPT（2026-11-12 01:07 UTC）

[下載 Open_Duck_Mini_v2_Assembly_Viewer.html](sandbox:/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html)

下載後直接用瀏覽器開啟。**模型、BOM、組裝照片和接線圖都在同一個 HTML 裡，可以離線使用。**

- **3D 爆炸與透視**：拖曳旋轉整隻鴨子，拉滑桿拆開零件，或把外殼變透明來看內部。點模型或 BOM 都能選取零件，再按「單獨查看」。
- **75 類 BOM**：包含原版 **51 件列印件、14 顆 STS3215 主舵機、2 顆天線舵機**，以及 Pi Zero 2 W、驅動板、IMU、電池、BMS、充電板、接頭與線束。可以直接搜 `ID 24` 找到左腳踝舵機。
- **14 步組裝指引**：從舵機編號與對零開始，每步都有零件、操作順序、驗收項目和原作者參考圖。接線頁也附有 GPIO 腳位表。genui{"citation":{"refs":["turn70view0","turn70view1"]}}

**裝配時以頁面上的精度標示為準。** 結構件和主舵機使用上游網格，部分電子板、線束和緊固件以示意呈現，孔位與走線請對照實物及原圖。我已檢查網格、BOM、爆炸位移和步驟連動。測試環境未能驗證本機 HTML 的 WebGL 畫面，檔案內也附了靜態組裝預覽。
