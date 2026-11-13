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
