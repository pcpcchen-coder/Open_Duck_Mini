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
 page.wait_for_function("document.documentElement.dataset.ready !== undefined",timeout=18000)
 assert page.locator('html').get_attribute('data-ready')=='true',page.locator('#scene-status').inner_text()
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
 page.locator('[data-bom="sts"]').click()
 expect(page.locator('.instance')).to_have_count(14)
 page.locator('[data-instance="servo-24"]').click()
 expect(page.locator('#selection strong')).to_have_text('ID 24 · 左腳踝舵機')
 page.locator('#only-focus').click()
 assert page.evaluate('''() => objects.filter(o=>o.group.visible).map(o=>o.part.id).join(',')==='servo-24' ''')
 page.screenshot(path='isolate-desktop.png')
 page.locator('#only-focus').click()
 page.locator('#search').fill('')
 page.locator('[data-step="9"]').click()
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
 page.locator('[data-step="12"]').click()
 assert page.locator('#wires').is_checked()
 page.reload(wait_until='load')
 expect(page.locator('#progress-text')).to_contain_text('1／14')
 assert not errors, errors
 assert not remote, remote
 phone=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True,offline=True)
 phone.goto(url,wait_until='load',timeout=25000)
 phone.wait_for_function("document.documentElement.dataset.ready === 'true'",timeout=16000)
 assert phone.evaluate('document.documentElement.scrollWidth')==390
 phone.screenshot(path='mobile.png')
 print('Offline, 3D modes, servo instance selection, isolation, step filter, GPIO, photos, progress reload and mobile passed.',flush=True)
 browser.close()
