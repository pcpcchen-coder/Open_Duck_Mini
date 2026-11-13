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
counts={k:int(n) for k,n in re.findall(r'([\w_]+)\.stl x(\d+)',(root/'docs/print_guide.md').read_text())}
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
 if st==7 and a!='body_middle_top':return '頭部關節'
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
 st=9 if bom[k]['cat']=='power' and k!='ubec' else 10 if g['body']=='head_assembly' or a=='antenna' else 8
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
 return json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
page=Path('index.template').read_text()
licenses='Open Duck Mini v2 — Antoine Pirrone and contributors\n\n'+(root/'LICENSE').read_text()
for name in ['three','fflate']:
 licenses+='\n\n'+Path('inspect/'+name+'-license.txt').read_text()
for token, content in {
 'STYLE':Path('viewer.css').read_text(),'THREE':Path('inspect/three.min.js').read_text(),
 'FFLATE':Path('inspect/fflate.js').read_text(),'DATA':jsjson(data),'GUIDE':Path('guide.js').read_text(),
 'VIEWER':Path('viewer.js').read_text(),'LICENSES':jsjson(licenses),
}.items():
 page=page.replace('{{'+token+'}}',lambda_value if False else content,1)
dest=Path('/mnt/data/Open_Duck_Mini_v2_Assembly_Viewer.html')
dest.write_text(page)
print(dest,dest.stat().st_size)
