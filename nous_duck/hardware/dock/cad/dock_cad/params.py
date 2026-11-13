"""充電座與背殼改裝的全部尺寸（單位 mm）。

座標系有兩個：

1. **充電座座標（dock frame）**：鴨子停好時，
   - X 朝前（從椅背指向房間，也就是鴨子面朝的方向），
   - Y 朝鴨子的左邊，
   - Z 朝上，Z = 0 是地板，
   - X = 0 是鴨子背後觸點凸台的外表面（停好時），Y = 0 是鴨子中線。
2. **上游列印座標（print frame）**：`print/body_back.stl` 原本的座標。背殼改裝件
   `body_back_dock.stl` 沿用這個座標，方便和原檔比對。

鴨子的站姿用上游 Open_Duck_Playground 的 `home` keyframe（步態策略的起始姿態），
從上游 MJCF 算出（見 `duck.py`）。所有「鴨子在哪裡」的數字都由程式計算，不手抄。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 列印限制
# ---------------------------------------------------------------------------
#: 每個零件在列印方向下的外框上限（X、Y、Z 都要小於等於這個值）。
#: 200 mm 可以放進 Prusa MK4、Ender-3 系列、Bambu Lab P1／X1／A1 的列印範圍。
BED_LIMIT = 200.0

# ---------------------------------------------------------------------------
# 背殼改裝（print frame）
# ---------------------------------------------------------------------------
#: 原版背殼平面背板的外表面（print frame 的 x）。
BACK_FLAT_X = -135.0
#: 平面背板的半寬；|y| 超過這個值就進入 45° 斜角。
BACK_FLAT_HALF_W = 15.0
#: 斜角壁厚（沿 x 量測，從 STL 量得 4.2 mm）。
BACK_CHAMFER_WALL = 4.2

#: 觸點凸台突出平面背板的距離。
BOSS_PROTRUDE = 8.0
#: 凸台外表面（print frame x）＝充電座座標 X = 0。
BOSS_FACE_X = BACK_FLAT_X - BOSS_PROTRUDE  # -143
#: 凸台正面半寬；之外是 45° 導角（給充電座的 V 形槽對中）。
BOSS_FACE_HALF_W = 28.0
#: 凸台總半寬。要小於背殼側面固定螺絲沉頭孔的內緣（|y| ≈ 41），留出螺絲起子空間。
BOSS_HALF_W = 38.0
#: 凸台 z 範圍（print frame）。平面背板大約在 z = -70～-2 之間。
BOSS_Z0 = -70.0
BOSS_Z1 = -2.0

#: 觸片（黃銅片）尺寸：寬 × 長 × 厚。
STRIP_W = 10.0
STRIP_L = 42.0
STRIP_T = 0.8
#: 觸片中心的 |y|（兩片：+y 為正極、-y 為負極）。
STRIP_Y = 10.0
#: 觸片的 z 範圍（print frame）。
STRIP_Z0 = -50.0
STRIP_Z1 = STRIP_Z0 + STRIP_L  # -8
#: 觸片槽比觸片大的間隙、槽深（觸片會凸出 0.2 mm）。
STRIP_POCKET_CLEAR = 0.2
STRIP_POCKET_DEPTH = 0.6

#: 走線槽（凸台正面下緣，導線藏在裡面再用熱熔膠封住）。
GROOVE_Z0 = -56.0
GROOVE_Z1 = -53.0
GROOVE_DEPTH = 2.5
#: 原版背殼 -y 斜角上原有的 Ø6 圓孔（從 STL 量得，中心約 y=-35.5、z=-23.8，深約 13 mm；
#: 用途待依上游組裝確認）。凸台在這裡沿孔的軸線（斜角法向）留 Ø8 通道，保持暢通。
SIDE_HOLE_Y = -35.5
SIDE_HOLE_Z = -23.8
SIDE_HOLE_CLEAR_D = 8.0
#: 穿進機身的線孔：在 -y 那側的斜角（USB-C 充電板在那一側）。
WIRE_HOLE_Y = -35.0
WIRE_HOLE_D = 4.0

# ---------------------------------------------------------------------------
# 充電座（dock frame）
# ---------------------------------------------------------------------------
#: 椅背正面（V 形導引座裝在這個面上）。
BACK_FRONT_X = -12.0
#: 底座與中椅背的後面。
BACK_REAR_X = -62.0
#: 上椅背／屋頂的後面（比下椅背薄）。
UPPER_REAR_X = -42.0
#: 椅背中段半寬。
BACK_HALF_W = 100.0
#: 椅背分段高度：底座（電子艙）、中椅背（V 形座）、上椅背（AprilTag）、屋頂。
#: 分段讓每一件都 ≤ 200 mm，而且 V 形座的調整範圍完整落在中椅背上。
PLINTH_TOP_Z = 60.0
MID_TOP_Z = 260.0
UPPER_TOP_Z = 420.0
ROOF_EAVE_Z = 442.0
ROOF_RIDGE_Z = 510.0
#: 殼厚。
WALL = 2.0
FRONT_WALL = 3.0

#: V 形導引座（cradle）。
#: 底面（凸台停止面）在 X = -1：凸台最多退到這裡（硬停止）。
CRADLE_BASE_X = -1.0
#: V 形牆與凸台 45° 導角之間的間隙（沿 X 量）。
CRADLE_CLEAR = 2.0
#: V 形牆外端的 |Y| 與 X。
CRADLE_TIP_HALF_W = 72.0
CRADLE_HALF_W = 78.0
#: 導引座高度（z 範圍以觸片中心為準上下各延伸）。
CRADLE_HEIGHT = 100.0
#: 導引座可上下微調的範圍（長槽孔，±）。
CRADLE_ADJUST = 15.0

#: 彈簧頂針（pogo pin）。
PIN_BORE = 3.1  # 依實際買到的頂針外徑調整
PIN_PROTRUDE = 3.5  # 頂針尖端在自由狀態凸出 V 形座底面的距離（要小於頂針行程）
PIN_Z_SPACING = 21.0  # 同一極兩支頂針的上下間距

#: 扶手。
ARM_INNER_Y = 165.0
ARM_THICK = 16.0
ARM_FRONT_X = 136.0
ARM_TOP_Z = 125.0
ARM_ROLL_R = 11.0

#: AprilTag（tag36h11），黑框邊長；整張含白邊是 10/8 倍。
TAG_FAMILY = "tag36h11"
TAG_ID = 0
TAG_BLACK_SIZE = 100.0
TAG_CENTER_Z = 340.0
#: 對位框溝：深、寬、與紙邊的間隙。
TAG_RECESS_DEPTH = 0.8
TAG_GUIDE_GROOVE = 1.2
TAG_RECESS_MARGIN = 1.0

#: 屋頂窗（狀態燈）。
WINDOW_D = 34.0
WINDOW_Z = 468.0

#: 外掛觸點板的螺絲穿孔。
M3_CLEAR_PLATE = 3.4
#: 熱熔螺帽（M3）孔、M3 穿孔。
INSERT_D = 4.0
INSERT_DEPTH = 6.0
M3_CLEAR = 3.4

