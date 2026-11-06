# SPDX-License-Identifier: MIT
"""UI20 visual controls and single-result feedback in real Chromium.

Production frontend and CSP, synthetic host responses. No storage or Docker
operations are executed on the host.
"""
import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from test_ui18_browser import API as DockerAPI, ERUGO, IMAGE, SECOND_IMAGE, ROOT
from test_ui17_browser import API as ImageAPI
from test_ui13_browser import CSP


class API(DockerAPI, ImageAPI):
    def __init__(self):
        super().__init__()
        self.monitor['legacy'] = False
        self.progress = None
        self.disk_error = 'This storage is in use. Stop the application using it, then try again.'

    def reply(self, req):
        action = urlsplit(req['url']).path.rsplit('/', 1)[-1]
        if self.session and action == 'disk-operation' and (req.get('data') or {}).get('action') == 'reconnect':
            self.calls.append((req['method'], 'legacy', action, copy.deepcopy(req['data'])))
            return dict(status=200, body=dict(ok=False, message='USB reconnect is unavailable while another application holds this disk.'))
        response = super().reply(req)
        if self.progress and response['status'] == 200:
            if action == 'status' and '/legacy/' in req['url']:
                response['body']['progress'] = copy.deepcopy(self.progress)
            if action == 'fleet-status':
                next(d for d in response['body']['drives'] if d['profile_id'] == 'legacy')['progress'] = copy.deepcopy(self.progress)
        return response


def run():
    shots = Path(os.environ.get('USW_UI20_SCREENSHOTS', '/tmp/usw-ui20-shots'))
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API(); errors = []; csp_errors = []; held = []; hold = [False]
            context = browser.new_context(has_touch=True, locale='en-US', timezone_id='Europe/Zagreb',
                                          viewport=dict(width=width, height=1000))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store'}

            def serve(route):
                req = route.request; path = urlsplit(req.url).path
                if path.startswith('/api/'):
                    request = dict(url=req.url, method=req.method,
                                   data=req.post_data_json if req.method == 'POST' else None)
                    if hold[0] and path.endswith('/docker-container-action'):
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
            page.on('console', lambda message: csp_errors.append(message.text)
                    if message.type == 'error' and 'Content Security Policy' in message.text else None)
            page.goto('http://192.168.50.24:8765/')
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)

            def nav(where):
                page.evaluate('(r)=>navigate(r)', where)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=where)

            def confirm():
                page.locator('#modal-root [data-action="confirmed-action"]').tap()
                page.wait_for_function('()=>!apiBusy&&!modalPending')

            def dismiss():
                page.locator('#modal-root [data-action="close-modal"]').first.tap()

            def no_overflow():
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width

            # US browser locale must never switch the app back to AM/PM or 24:00.
            times = page.evaluate('()=>[ago(),humanTime("2026-11-02T22:05:06Z"),humanTime("2026-11-01T23:00:00Z")]')
            assert all(not re.search(r'\b[AP]M\b', value) for value in times), times
            assert '23:05:06' in times[1], times
            assert '00:00:00' in times[2], times
            start = page.locator('[data-drive-card="legacy"] [data-action="toggle-monitoring"]')
            expect(start).to_have_text('Start monitoring')
            assert start.evaluate('(b)=>getComputedStyle(b).backgroundColor') == 'rgb(18, 61, 45)'
            assert start.evaluate('(b)=>parseFloat(getComputedStyle(b).borderTopWidth)') == 2

            nav('drive/legacy')
            group = page.locator('#drive-summary>.actions')
            # A refusal followed by a different refusal replaces the first message.
            group.locator('[data-action="toggle-mount"]').tap(); confirm(); dismiss()
            expect(group.locator('[data-action-status]:visible')).to_have_count(1)
            expect(group.locator('[data-action-status]:visible')).to_contain_text(api.disk_error)
            # UI25: mounted storage must disable manual USB reset before any action.
            expect(group.locator('[data-action="reconnect-drive"]')).to_be_disabled()
            expect(group.locator('[data-action-status]:visible')).to_have_count(1)
            expect(group.locator('[data-action-status]:visible')).to_contain_text(api.disk_error)
            expect(page.locator('[data-last-operation]')).to_have_count(0)
            # A subsequent monitoring action replaces the error, including after rerender/poll.
            group.locator('[data-action="toggle-monitoring"]').tap()
            page.wait_for_function('()=>!apiBusy')
            expect(group.locator('[data-action-status]:visible')).to_have_count(1)
            expect(group.locator('[data-action-status]:visible')).not_to_contain_text(api.disk_error)
            page.evaluate('()=>render()')
            expect(group.locator('[data-action-status]:visible')).to_have_count(1)
            status_box = group.locator('[data-action-status]:visible').bounding_box()
            assert status_box['width'] >= group.bounding_box()['width'] - 3
            assert status_box['y'] >= max(b.bounding_box()['y'] + b.bounding_box()['height'] for b in group.locator('button').all()) - 1
            no_overflow()
            if width in (390, 1440):
                page.screenshot(path=str(shots/f'single-drive-result-{width}.png'), full_page=True)

            # Polling shows the current automatic stage in the same single-result row.
            stages = [
                ('waiting_manual', 'Waiting for manual mount', 'Automatic disk mounting is off. Containers remain stopped.', False),
                ('waiting_return', 'Waiting for disk', 'Selected containers are stopped. Reconnect this disk.', False),
                ('running', 'Mounting recovered disk', 'Mount <disk> & verify filesystem identity.', True),
                ('applications', 'Starting selected containers', 'Selected virtual images are mounted.', True),
            ]
            for code, title, detail, busy in stages:
                api.progress = dict(incident='synthetic-incident', code=code, title=title, detail=detail)
                page.evaluate('()=>pollLive()')
                status = group.locator('[data-recovery-progress]')
                expect(status).to_have_attribute('data-recovery-progress', code)
                expect(status).to_contain_text(title)
                expect(status).to_contain_text(detail)
                expect(status).to_have_attribute('aria-busy', str(busy).lower())
                expect(status.locator('disk')).to_have_count(0)
                expect(group.locator('[role="status"]:visible')).to_have_count(1)
                expect(group.locator('[data-action-status]:visible')).to_have_count(0)
                expect(page.locator('[data-last-operation]')).to_have_count(0)
                assert status.bounding_box()['width'] >= group.bounding_box()['width'] - 3
                no_overflow()
            if width in (390, 1440):
                page.screenshot(path=str(shots/f'live-recovery-{width}.png'), full_page=True)
            api.progress = dict(incident='synthetic-incident', code='recovered', title='Recovered', detail='Storage is healthy.')
            page.evaluate('()=>pollLive()')
            expect(group.locator('[data-recovery-progress]')).to_have_count(0)
            expect(group.locator('[role="status"]:visible')).to_have_count(0)
            group.locator('[data-action="toggle-monitoring"]').tap()
            page.wait_for_function('()=>!apiBusy')
            expect(group.locator('[data-action-status]:visible')).to_have_count(1)

            nav('apps')
            card = page.locator(f'[data-container-id="{ERUGO}"]')
            header = card.locator('.docker-container-header')
            assert header.evaluate('(b)=>getComputedStyle(b).backgroundColor') == 'rgb(21, 43, 70)'
            assert card.evaluate('(b)=>getComputedStyle(b).backgroundColor') != 'rgb(21, 43, 70)'
            expect(card).to_contain_text('detect failure → stop this container → unmount failed storage → recover and mount the disk')
            expect(card).to_contain_text('If a selected image cannot be mounted, this container stays stopped.')
            expect(card).not_to_contain_text('continue with the restart')
            expect(card.locator('[data-docker-control-status]:visible')).to_have_count(0)
            # Pending status and a refusal each appear once below the manual controls.
            hold[0] = True
            card.locator('[data-action="docker-start"]').tap()
            expect(card.locator('[data-docker-control-status]')).to_contain_text('Starting')
            expect(card.locator('.docker-manual-controls [role="status"]:visible')).to_have_count(1)
            expect(card.locator('[data-action="docker-start"]')).to_be_disabled()
            card.locator('[data-action="docker-start"]').evaluate('(b)=>b.click()')
            assert len(held) == 1
            header.tap(); header.tap()
            expect(card.locator('[data-docker-control-status]')).to_contain_text('Starting')
            api.control_mode = 'refused'; hold[0] = False
            route, request = held.pop(); response = api.reply(request)
            route.fulfill(status=response['status'], json=response['body'], headers=headers)
            expect(card.locator('[data-docker-control-status]')).to_contain_text('Docker refused')
            expect(card.locator('.docker-manual-controls [role="status"]:visible')).to_have_count(1)
            expect(card.locator('.docker-manual-controls [data-action-status]')).to_have_count(0)
            # Recovery choices remain editable with monitoring off and runtime errors.
            api.monitor = {key: False for key in api.monitor}
            checkbox = card.locator(f'[data-change="docker-image"][value="{SECOND_IMAGE}"]')
            checkbox.check()
            expect(card.locator('[data-action="docker-save"]')).to_be_enabled()
            api.control_mode = ''
            card.locator('[data-action="docker-start"]').tap()
            expect(card.locator('.docker-live-state')).to_contain_text('Running')
            expect(card.locator('[data-docker-control-status]')).to_contain_text('started')
            expect(card.locator('.docker-manual-controls [role="status"]:visible')).to_have_count(1)
            expect(checkbox).to_be_checked()
            assert not re.search(r'\b[AP]M\b', page.locator('#docker-refresh-status').inner_text())
            no_overflow()
            if width in (390, 1440):
                page.screenshot(path=str(shots/f'docker-header-and-result-{width}.png'), full_page=True)
            assert not errors, errors
            assert not csp_errors, csp_errors
            context.close()
            print(f'PASS UI20 {width}px: requested colors, 24-hour times, one latest drive/manual Docker result, readable feedback, live recovery stages, busy guard, collapses and drafts')
        browser.close()


if __name__ == '__main__':
    run()
