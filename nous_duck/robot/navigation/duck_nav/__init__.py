"""duck_nav：鴨子的導航核心（定位、規劃、任務、回充、安全）。

只依賴 numpy 與標準函式庫，**不依賴 MuJoCo**；對外只有兩個抽象：
`SensorFrame`（感測輸入）與 `NavOutput`（速度指令＋頭部目標＋事件）。見 `../README.md`。
"""

NAV_SOFTWARE = "duck_nav/0.1"
