"""UI7 Chromium workflows; synthetic API, no host disk or service operations."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_approved_ui_live import MockBroker, ROOT as DEFAULT_ROOT

ROOT = Path(os.environ['USW_GUI_PAYLOAD']) / 'web_static' if os.environ.get('USW_GUI_PAYLOAD') else DEFAULT_ROOT


class API(MockBroker):
    def __init__(self):
        super().__init__()
        self.last = None
        self.succeed = False
        self.fail_reads = False
        self.break_reads_after_action = False

    def reply(self, request):
        action = request['url'].split('?')[0].split('/')[-1]
        if self.session and action == 'disk-operation':
            drive = request['url'].split('/api/drives/')[1].split('/')[0]
            self.calls.append((request['method'], drive, action, request['data']))
            self.mounted[drive] = self.succeed
            self.monitor[drive] = self.succeed
            message = ('Software USB reconnect completed. Electrical power removal is not verified.' if self.succeed else
                       'USB reconnect was not performed. No USB disconnect write was started. Monitoring is paused.')
            self.last = dict(uuid=self.drives[drive][1], action='reconnect', ok=self.succeed,
                             message=message, time='2026-11-01T00:00:00Z')
            self.fail_reads = self.break_reads_after_action
            return dict(status=200, body=dict(ok=self.succeed, message=message, last_operation=self.last))
        if self.session and self.fail_reads and action in ('status', 'fleet-events'):
            return dict(status=503, body=dict(error='Synthetic readback unavailable'))
        response = super().reply(request)
        if response['status'] == 200 and action == 'status':
            response['body']['last_operation'] = self.last if '/legacy/' in request['url'] else None
            response['body']['usb']['message'] = 'Software reconnect available, subject to live safety checks.'
        if response['status'] == 200 and action == 'fleet-events' and self.last:
            response['body']['events'].insert(0, dict(drive_id='legacy', time=self.last['time'],
                title='Manual USB port reconnect — ' + ('Successful' if self.last['ok'] else 'Failed'),
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
            button = page.locator('[data-action="reconnect-drive"]')
            expect(button).to_have_text('Reconnect USB (software)')
            expect(page.get_by_text('Unavailable in this build — power removal is not verified.')).to_be_visible()

            def reconnect():
                button.click()
                expect(page.get_by_role('heading', name='Reconnect USB in software?')).to_be_visible()
                expect(page.locator('#modal-root')).to_contain_text('a separate disk power supply is not controlled')
                page.locator('#modal-root [data-action="confirmed-action"]').click()
                expect(page.locator('#modal-root')).to_be_empty()
                page.wait_for_function('() => !apiBusy')

            reconnect()
            expect(page.locator('.toast.error').filter(has_text='No USB disconnect write was started')).to_have_count(1)
            expect(page.locator('.toast:not(.error)')).to_have_count(0)
            expect(page.locator('[data-last-operation="failed"]')).to_contain_text('Monitoring is paused')
            expect(page.locator('#drive-recent-events')).to_contain_text('Manual USB port reconnect — Failed')
            expect(page.locator('[data-action="toggle-monitoring"]')).to_have_text('Start monitoring')
            expect(page.locator('[data-action="toggle-mount"]')).to_have_text('Mount drive')
            assert api.mounted['drive-b'] is True and api.monitor['drive-b'] is False
            assert len([call for call in api.calls if call[2] == 'disk-operation']) == 1
            screenshot_dir = os.environ.get('USW_UI7_SCREENSHOTS')
            if screenshot_dir and width in (320, 390, 1440):
                Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshot_dir) / f'ui7-result-{width}.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('''()=>Array.from(document.querySelectorAll('#main-content *')).filter(el=>el.getBoundingClientRect().right>innerWidth).map(el=>({tag:el.tagName,cls:el.className,width:el.getBoundingClientRect().width,text:el.innerText?.slice(0,90)}))''')

            # A status refresh retains the authoritative last result.
            page.evaluate("async()=>{await refreshDetail('legacy');}")
            expect(page.locator('[data-last-operation="failed"]')).to_be_visible()
            api.succeed = True
            page.evaluate("document.querySelector('#toasts').replaceChildren()")
            reconnect()
            expect(page.locator('[data-last-operation="success"]')).to_contain_text('Electrical power removal is not verified')
            expect(page.locator('.toast:not(.error)')).to_have_count(1)
            expect(page.locator('.toast.error')).to_have_count(0)

            # A successful operation remains successful when later status reads fail.
            api.break_reads_after_action = True
            page.evaluate("document.querySelector('#toasts').replaceChildren()")
            reconnect()
            expect(page.locator('[data-last-operation="success"]')).to_be_visible()
            expect(page.locator('.toast.error')).to_contain_text('Some status or history could not be refreshed')
            assert len([call for call in api.calls if call[2] == 'disk-operation']) == 3
            assert page.evaluate('find("legacy").stale') is True
            assert not errors, errors
            print(f'PASS UI7 browser {width}px: failed/successful result, persisted status, power notice, refresh failure, drive isolation')
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
