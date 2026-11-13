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
