"""UI8 sleep workflows in Chromium, with synthetic API and no disk operations."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_approved_ui_live import MockBroker, ROOT as DEFAULT_ROOT

ROOT = Path(os.environ['USW_GUI_PAYLOAD']) / 'web_static' if os.environ.get('USW_GUI_PAYLOAD') else DEFAULT_ROOT


class API(MockBroker):
    def __init__(self):
        super().__init__()
        self.last = None
        self.outcome = 'success'
        self.standby = 'idle'
        _, uuid, _ = self.drives['legacy']
        self.drives['legacy'] = ('Synthetic USB HDD', uuid, 500_000_000_000)

    def reply(self, request):
        action = request['url'].split('?')[0].split('/')[-1]
        if self.session and action == 'disk-operation':
            drive = request['url'].split('/api/drives/')[1].split('/')[0]
            assert drive == 'legacy' and request['data']['action'] == 'sleep'
            self.calls.append((request['method'], drive, action, request['data']))
            success = self.outcome == 'success'
            message = {
                'success': 'HDD standby confirmed. The filesystem remains mounted; new access may wake it.',
                'busy': 'Disk activity did not settle within 15 seconds after flushing writes; standby was not sent.',
                'unsupported': 'USB-SATA bridge rejected the power command; standby could not be verified.',
                'uncertain': 'Sleep request failed or timed out; HDD power state is unverified. No automatic retry was sent.',
            }[self.outcome]
            message += ' Monitoring is ' + ('on' if self.monitor[drive] else 'off') + '; the sleep request did not change it.'
            self.standby = 'standby' if success else 'active'
            self.last = dict(uuid=self.drives[drive][1], action='sleep', ok=success,
                             message=message, time='2026-11-01T01:00:00Z')
            return dict(status=200, body=dict(ok=success, message=message, last_operation=self.last))
        response = super().reply(request)
        if response['status'] == 200 and action == 'fleet-status':
            response['body']['drives'][0]['media_kind'] = 'hdd'
        if response['status'] == 200 and action == 'status' and '/legacy/' in request['url']:
            response['body']['discovered']['media_kind'] = 'hdd'
            response['body']['last_operation'] = self.last
            response['body']['standby'] = dict(state=self.standby, applicable=True, enabled=False,
                                               sleeping=self.standby == 'standby', idle_seconds=1800)
        if response['status'] == 200 and action == 'fleet-events' and self.last:
            response['body']['events'].insert(0, dict(drive_id='legacy', time=self.last['time'],
                title='Manual HDD standby — ' + ('Successful' if self.last['ok'] else 'Failed'),
                detail=self.last['message']))
        return response


def run():
    html = (ROOT / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">', '').replace('<script src="/static/app.js" defer></script>', '')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
                                             headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context()
        for width in (320, 390, 768, 1440):
            api = API()
            page = context.new_page()
            page.set_viewport_size(dict(width=width, height=900))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content(html)
            page.add_style_tag(content=(ROOT / 'style.css').read_text())
            page.expose_binding('synthetic_api', lambda _source, request: api.reply(request))
            page.evaluate('''() => {window.fetch=async(url,options={})=>{
              const result=await window.synthetic_api({url:String(url),method:options.method||'GET',data:options.body?JSON.parse(options.body):null});
              return new Response(JSON.stringify(result.body),{status:result.status,headers:{'Content-Type':'application/json'}});
            }}''')
            page.add_script_tag(content=(ROOT / 'app.js').read_text())
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').click()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.locator('[data-drive-card="legacy"] [data-action="manage-drive"]').click()

            for monitoring, outcome in ((True, 'success'), (True, 'busy'), (True, 'unsupported'),
                                        (True, 'uncertain'), (False, 'success'), (False, 'busy')):
                api.monitor['legacy'] = monitoring
                api.outcome = outcome
                page.evaluate("async()=>{await refreshFleet({display:false});await refreshDetail('legacy');render();document.querySelector('#toasts').replaceChildren();}")
                page.locator('[data-action="sleep-hdd"]').click()
                expect(page.get_by_role('heading', name='Sleep HDD now?')).to_be_visible()
                expect(page.locator('#modal-root')).to_contain_text('Monitoring stays in its current state')
                expect(page.locator('#modal-root')).to_contain_text('up to 15 seconds')
                page.locator('#modal-root [data-action="confirmed-action"]').click()
                expect(page.locator('#modal-root')).to_be_empty()
                page.wait_for_function('() => !apiBusy')
                expected = 'success' if outcome == 'success' else 'failed'
                expect(page.locator(f'[data-last-operation="{expected}"]')).to_contain_text('sleep request did not change it')
                expect(page.locator('[data-action="toggle-monitoring"]')).to_have_text('Stop monitoring' if monitoring else 'Start monitoring')
                expect(page.locator('[data-action="toggle-mount"]')).to_have_text('Unmount safely')
                expect(page.locator('.toast.error')).to_have_count(0 if outcome == 'success' else 1)
                expect(page.locator('.toast:not(.error)')).to_have_count(1 if outcome == 'success' else 0)
                if outcome == 'success':
                    expect(page.get_by_text('HDD: Spun down', exact=True)).to_be_visible()
                expect(page.locator('#drive-recent-events')).to_contain_text('Manual HDD standby')
                page.evaluate("async()=>{await refreshDetail('legacy');}")
                expect(page.locator(f'[data-last-operation="{expected}"]')).to_be_visible()
                assert api.monitor['legacy'] is monitoring and api.mounted['legacy'] is True
                assert api.monitor['drive-b'] is False and api.mounted['drive-b'] is True
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                screenshot_dir = os.environ.get('USW_UI8_SCREENSHOTS')
                if screenshot_dir and monitoring and outcome == 'success' and width in (390, 1440):
                    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(screenshot_dir) / f'ui8-sleep-{width}.png'), full_page=True)
            assert len([call for call in api.calls if call[2] == 'disk-operation']) == 6
            assert not any(call[2] == 'monitor' for call in api.calls)
            assert not errors, errors
            print(f'PASS UI8 browser {width}px: sleep success/refusal/unsupported/timeout, monitoring on/off, mounted state, history, drive isolation')
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
