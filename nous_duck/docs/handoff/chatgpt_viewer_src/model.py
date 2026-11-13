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
drives=[g for g in geoms if g['asset']=='drive_palonier']
mset=[[g] for g in drives]
for g in geoms:
 if g['asset'].startswith('wj-') or g['asset']=='passive_palonier':
  i=min((i for i,h in enumerate(drives) if h['body']==g['body']),key=lambda i: np.linalg.norm(drives[i]['p']-g['p']))
  mset[i].append(g)
motor_ids={'left_hip_yaw':20,'left_hip_roll':21,'left_hip_pitch':22,'left_knee':23,'left_ankle':24,
'right_hip_yaw':10,'right_hip_roll':11,'right_hip_pitch':12,'right_knee':13,'right_ankle':14,
'neck_pitch':30,'head_pitch':31,'head_yaw':32,'head_roll':33}
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
