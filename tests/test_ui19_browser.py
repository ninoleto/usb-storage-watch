# SPDX-License-Identifier: MIT
"""Long mount feedback and truthful mount conflicts in the real UI.
All host responses are synthetic; no disk or container is operated.
"""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui17_browser import API as PreviousAPI, ROOT
from test_ui13_browser import CSP

LONG_ERROR = ('Target/submount or expected device is already active; no mount/remount allowed. '
              'Main Storage filesystem unavailable. Monitoring is paused.')
CONFLICT = ('The configured folder /mnt/legacy is still occupied by ext4 device 8:17, '
            'but this drive now resolves to device 8:49. The existing mount must be identified '
            'and released before the returned drive can be mounted.')


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.mounted['legacy'] = False
        self.conflict = True
        self.disk_error = LONG_ERROR

    def reply(self, req):
        path = urlsplit(req['url']).path
        action = path.rsplit('/', 1)[-1]
        data = req.get('data') or {}
        if self.session and action == 'disk-operation' and data.get('action') == 'reconnect':
            self.calls.append((req['method'], 'legacy', action, copy.deepcopy(data)))
            return dict(status=200, body=dict(ok=False, message='Unexpected mount identity/type/root; '
                        'manual intervention required. Monitoring is paused.'))
        response = super().reply(req)
        if response['status'] == 200 and self.conflict:
            fields = dict(mount_state='conflict', mount_detail=CONFLICT, mount_target_occupied=True)
            if action == 'fleet-status':
                next(r for r in response['body']['drives'] if r['profile_id'] == 'legacy').update(fields)
            if action == 'status' and '/legacy/' in path:
                response['body'].update(fields)
        return response


def run():
    shots = Path('/tmp/usw-ui19-shots'); shots.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
                                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API(); errors = []; csp = []; held = []
            hold = [False]
            context = browser.new_context(has_touch=True, viewport=dict(width=width, height=1000))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store'}

            def serve(route):
                req = route.request; path = urlsplit(req.url).path
                if path.startswith('/api/'):
                    request = dict(url=req.url, method=req.method,
                                   data=req.post_data_json if req.method == 'POST' else None)
                    if hold[0] and path.endswith('/disk-operation'):
                        held.append((route, request)); return
                    response = api.reply(request)
                    route.fulfill(status=response['status'], json=response['body'], headers=headers); return
                name = 'index.html' if path == '/' else path.removeprefix('/static/')
                if name not in ('index.html', 'app.js', 'network.js', 'style.css', 'icon.svg'):
                    route.fulfill(status=404, body=''); return
                route.fulfill(path=str(ROOT/name), headers=headers,
                              content_type='text/html' if name.endswith('html') else
                              'text/javascript' if name.endswith('js') else
                              'text/css' if name.endswith('css') else 'image/svg+xml')

            context.route('**/*', serve)
            page = context.new_page(); page.set_default_timeout(12000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: csp.append(msg.text) if msg.type == 'error' and 'Content Security Policy' in msg.text else None)
            page.goto('http://192.168.50.24:8765/')
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            card = page.locator('[data-drive-card="legacy"]')
            expect(card.locator('.chip', has_text='Mount conflict')).to_be_visible()
            expect(card.locator('.mount-state-notice')).to_contain_text(CONFLICT)
            expect(card.locator('.chip', has_text='Unmounted')).to_have_count(0)

            def nav(destination):
                page.evaluate('(r)=>navigate(r)', destination)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=destination)

            def feedback(button):
                return button.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " action-control ")][1]').locator('[data-action-status]')

            def readable(status, group):
                s, g = status.bounding_box(), group.bounding_box()
                assert s and g and s['width'] >= g['width'] - 3, (width, s, g)
                assert s['height'] <= 150, (width, s)
                buttons = group.locator('button').all()
                bottom = max(b.bounding_box()['y'] + b.bounding_box()['height'] for b in buttons)
                assert s['y'] >= bottom - 1, (width, s, bottom)
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width

            nav('drive/legacy')
            expect(page.locator('#drive-summary .chip', has_text='Mount conflict')).to_be_visible()
            expect(page.locator('#drive-summary .mount-state-notice')).to_contain_text(CONFLICT)
            expect(page.locator('[data-action="mount-location"]')).to_be_disabled()
            expect(page.locator('#drive-summary')).to_contain_text('Mount conflict — see details below')
            mount = page.locator('[data-action="toggle-mount"]')
            reconnect = page.locator('[data-action="reconnect-drive"]')
            x_before = reconnect.bounding_box()['x']
            mount.tap()
            confirm = page.locator('[data-action="confirmed-action"]')
            hold[0] = True; confirm.tap()
            expect(confirm).to_be_disabled()
            expect(feedback(confirm)).to_contain_text('Working')
            readable(feedback(confirm), page.locator('.modal-actions'))
            page.evaluate('()=>document.querySelector("[data-action=confirmed-action]").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
            assert len(held) == 1
            hold[0] = False
            route, request = held.pop()
            response = api.reply(request)
            route.fulfill(status=response['status'], json=response['body'], headers=headers)
            page.wait_for_function('()=>!apiBusy&&!modalPending')
            expect(feedback(confirm)).to_contain_text(LONG_ERROR)
            readable(feedback(confirm), page.locator('.modal-actions'))
            page.screenshot(path=str(shots/f'long-modal-{width}.png'), full_page=True)
            page.locator('[data-action="close-modal"]').tap()
            expect(feedback(mount)).to_contain_text(LONG_ERROR)
            expect(feedback(mount)).to_contain_text('Mount drive:')
            readable(feedback(mount), page.locator('#drive-summary>.actions'))
            assert abs(reconnect.bounding_box()['x'] - x_before) < 2
            page.evaluate('()=>render()')
            readable(feedback(mount), page.locator('#drive-summary>.actions'))
            page.screenshot(path=str(shots/f'long-drive-{width}.png'), full_page=True)
            assert not errors, errors
            assert not csp, csp
            context.close()
            print(f'PASS UI19 {width}px: long errors span action row/dialog, stable buttons, pending/duplicate guards, truthful mount conflict and blocked location change')
        browser.close()


if __name__ == '__main__':
    run()
