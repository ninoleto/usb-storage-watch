# SPDX-License-Identifier: MIT
"""Touch removal through real HTTP/broker routes; synthetic disks and systemd."""
import os
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
from gui_fixture import Machine, UUID
from multidrive_fixture import FleetMachine


class Quiet(WSGIRequestHandler):
    def log(self,*a,**kw):pass


def run():
    shots=Path(os.environ.get('USW_UI14_SCREENSHOTS','/tmp/usw-ui14-shots'));shots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        for width in (320,390,768,1440):
            f=FleetMachine();profile=f.add();m=f.main;hdd=f.second;hdd.active=True;errors=[];posts=[];fail_stop=[False]
            c=hdd.b.configuration();c['disk']['label']='TOSHIBA test HDD';hdd.b.cli.save(hdd.config,c);hdd.model='TOSHIBA test HDD'
            for machine in (m,hdd):
                command=machine.command
                def verified(args,timeout=10,machine=machine,command=command):
                    if fail_stop[0] and machine is m and args[:2]==['/usr/bin/systemctl','disable']:raise ValueError('Synthetic stop failure')
                    value=command(args,timeout)
                    if args[:2]==['/usr/bin/systemctl','show']:value+='\nMainPID='+('111' if machine.active else '0')
                    return value
                machine.patch(machine.b,'command',verified)
            token=m.management_token()
            server=make_server('127.0.0.1',0,lambda e,s:[],threaded=True,request_handler=Quiet)
            server.app=m.web.create_app(dict(m.b.common.DEFAULT,port=server.server_port),m.broker.handle)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            context=browser.new_context(has_touch=True,viewport=dict(width=width,height=1000))
            page=context.new_page();page.set_default_timeout(12000);page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and r.url.endswith('/remove-drive') else None)
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                page.goto(base);page.locator('#usw-login-token').fill(token);page.locator('#usw-login-form button').tap()
                expect(page.locator('[data-drive-card]')).to_have_count(2)
                page.wait_for_function('()=>!apiBusy&&!routeLoading')
                card=page.locator('[data-drive-card="legacy"]')
                remove=card.get_by_role('button',name='Remove from Storage Watch',exact=True)
                assert remove.bounding_box()['height']>=48
                remove.tap();dialog=page.get_by_role('dialog',name='Remove ADATA USB Flash Drive?')
                expect(dialog).to_be_visible();expect(dialog).to_contain_text('Nothing is erased, formatted or unmounted.')
                dialog.get_by_role('button',name='Cancel',exact=True).tap()
                expect(dialog).to_have_count(0);assert posts==[] and m.active and hdd.active
                # A stop refusal stays visible beside the confirmation, with a fresh review for retry.
                fail_stop[0]=True;remove.tap();dialog.get_by_role('button',name='Remove from Storage Watch',exact=True).tap()
                expect(page.get_by_role('dialog',name='Removal not confirmed')).to_be_visible()
                expect(page.get_by_role('alert')).to_contain_text('Monitoring could not be stopped')
                assert m.config.exists() and m.active and hdd.active and len(posts)==1
                fail_stop[0]=False;page.get_by_role('button',name='Close',exact=True).tap()
                # Removing an unplugged legacy stick must keep the HDD and login alive.
                m.present=False;m.current=''
                page.get_by_role('button',name='Refresh drives',exact=True).tap();page.wait_for_function('()=>!apiBusy')
                expect(card).to_contain_text('Disconnected');remove.tap();expect(dialog).to_be_visible()
                # Hold an older complete list across the removal. It must not
                # resurrect the card after the newer authoritative list arrives.
                held=[]
                def stale_list(route):
                    response=route.fetch()
                    if not held:
                        held.append((route,response));page.evaluate('()=>window.staleFleetReady=true')
                    else:route.fulfill(response=response)
                page.route('**/api/fleet-status',stale_list)
                page.evaluate('()=>{void refreshFleet({display:false}).finally(()=>window.staleFleetDone=true)}')
                page.wait_for_function('()=>window.staleFleetReady===true')
                if width in (390,1440):page.screenshot(path=str(shots/f'remove-confirm-{width}.png'))
                # Lose the response after the real broker commits: the UI verifies the list,
                # does not repeat the POST, and does not keep a phantom overview card.
                def lose_receipt(route):route.fetch();route.abort()
                page.route('**/api/drives/legacy/remove-drive',lose_receipt)
                dialog.get_by_role('button',name='Remove from Storage Watch',exact=True).tap()
                expect(page.locator('[data-drive-card]')).to_have_count(1);expect(card).to_have_count(0)
                page.wait_for_function('()=>!apiBusy&&!routeLoading');assert len(posts)==2
                held[0][0].fulfill(response=held[0][1]);page.wait_for_function('()=>window.staleFleetDone===true')
                expect(card).to_have_count(0);page.unroute('**/api/fleet-status',stale_list)
                assert not m.config.exists() and not m.active and hdd.active
                expect(page.locator('[data-drive-card]')).to_contain_text('TOSHIBA test HDD')
                page.reload();expect(page.locator('[data-drive-card]')).to_have_count(1)
                assert page.locator('#usw-login').is_hidden()
                page.get_by_role('button',name='Refresh drives',exact=True).tap();page.wait_for_function('()=>!apiBusy')
                expect(page.locator('[data-drive-card]')).to_have_count(1)
                # The still-running HDD can also be retired from Manage Drive, including
                # the empty-fleet state. No mount or application operation is dispatched.
                page.get_by_role('button',name='Manage drive',exact=True).tap();page.wait_for_function('()=>!routeLoading')
                page.locator('.remove-drive-section').get_by_role('button',name='Remove from Storage Watch',exact=True).tap()
                page.get_by_role('dialog').get_by_role('button',name='Remove from Storage Watch',exact=True).tap()
                expect(page.get_by_text('No drives configured',exact=True)).to_be_visible()
                page.wait_for_function('()=>!apiBusy&&!routeLoading');assert not hdd.active
                # Explicit Add after removal creates a new identity with fresh defaults.
                m.present=True;m.current='/mnt/drive-a'
                def fresh(identifier):
                    child=Machine(root=m.root,identifier=identifier,uuid=UUID,mountpoint=m.current,model=m.model)
                    child.patch(child.b,'disks',f.disks);child.b.auth=m.b.auth;child.broker.sessions=m.broker.sessions
                    f.children[identifier]=child
                    return child.b,child.broker
                m.broker.fleet.factory=fresh
                page.get_by_role('button',name='Add USB drive',exact=True).tap()
                # Select by the exact candidate id emitted by the app, not its list position.
                choice=page.locator('[data-action="add-detected"][data-id="candidate-'+UUID+'"]')
                expect(choice).to_be_visible();choice.tap()
                page.wait_for_function('()=>!apiBusy&&!routeLoading')
                new_id=page.url.split('#drive/')[-1];assert new_id not in ('legacy',profile)
                expect(page.locator('#drive-summary')).to_contain_text('ADATA USB Flash Drive')
                assert len(m.broker.fleet.records())==1 and not f.children[new_id].active
                assert m.config.with_name('removed-drive.json').exists() and hdd.config.with_name('removed-drive.json').exists()
                page.get_by_role('button',name='Back to overview',exact=True).tap();page.wait_for_function('()=>!routeLoading')
                expect(page.locator('[data-drive-card]')).to_have_count(1)
                if width in (390,1440):page.screenshot(path=str(shots/f'removal-overview-{width}.png'))
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                print(f'PASS UI14 {width}px: real HTTP removal review/cancel/refusal, disconnected legacy removal, lost receipt without replay, reload persistence, Manage Drive/last-drive removal, explicit fresh re-add; other drive and global login preserved',flush=True)
            finally:
                context.close();server.shutdown();server.server_close();thread.join(5);f.close()
        browser.close()


if __name__=='__main__':run()
