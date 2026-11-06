# SPDX-License-Identifier: MIT
"""Manual container actions through the shipped UI with synthetic Docker APIs.

No real Docker container, host service, filesystem, or monitoring configuration
is changed. Chromium uses production CSP and the actual packaged frontend.
"""
import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from test_ui16_browser import API as PreviousAPI, ROOT, ERUGO, OTHER, IMAGE, SECOND_IMAGE
from test_ui13_browser import CSP


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.containers[0]['state'] = 'stopped'
        self.containers[1]['state'] = 'running'
        self.control_mode = ''
        self.control_error = ''
        self.action_counts = {ERUGO: 0, OTHER: 0}

    def container(self, identity):
        return next((row for row in self.containers if row['id'] == identity), None)

    def reply(self, req):
        action = urlsplit(req['url']).path.rsplit('/', 1)[-1]
        data = req.get('data') or {}
        if self.session and action == 'docker-container-action':
            self.calls.append((req['method'], None, action, copy.deepcopy(data)))
            assert req['method'] == 'POST'
            assert set(data) == {'id', 'name', 'action', 'confirm'}, data
            assert data['confirm'] is True and data['action'] in ('start', 'stop', 'restart')
            row = self.container(data['id'])
            if row is None or row['name'] != data['name']:
                return dict(status=400, body=dict(error='This container identity changed. Refresh before trying again.'))
            if self.control_error:
                return dict(status=400, body=dict(error=self.control_error))
            if self.control_mode == 'refused':
                return dict(status=200, body=dict(ok=False, uncertain=False,
                    message='Docker refused this action. No container action was completed.', container=row))
            if self.control_mode == 'uncertain':
                return dict(status=200, body=dict(ok=False, uncertain=True,
                    message='The Docker result is not confirmed. Refresh status before trying again; no request was repeated.', container=row))
            self.action_counts[row['id']] += 1
            row['state'] = 'stopped' if data['action'] == 'stop' else 'running'
            if self.control_mode == 'server-error':
                return dict(status=503, body=dict(error='Synthetic server error after Docker accepted the action.'))
            word = {'start': 'started', 'stop': 'stopped', 'restart': 'restarted'}[data['action']]
            return dict(status=200, body=dict(ok=True, uncertain=False,
                message='Container ' + word + '. Runtime status verified; file access was not tested.',
                container=copy.deepcopy(dict(row, discovered=True))))
        return super().reply(req)


def run():
    shots = Path(os.environ.get('USW_UI18_SCREENSHOTS', '/tmp/usw-ui18-shots'))
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API()
            errors, csp_errors, traffic, held, held_reads = [], [], [], [], []
            hold_id, lose_id, hold_read = [None], [None], [False]
            context = browser.new_context(has_touch=True, viewport=dict(width=width, height=1000))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store',
                       'X-Content-Type-Options': 'nosniff'}

            def serve(route):
                req = route.request
                path = urlsplit(req.url).path
                if path.startswith('/api/'):
                    request = dict(url=req.url, method=req.method,
                                   data=req.post_data_json if req.method == 'POST' else None)
                    action = path.rsplit('/', 1)[-1]
                    traffic.append((req.method, action, copy.deepcopy(request['data'])))
                    if action == 'docker-container-action' and request['data']['id'] == hold_id[0]:
                        held.append((route, request))
                        return
                    response = api.reply(request)
                    if action == 'docker-overview' and hold_read[0]:
                        hold_read[0] = False
                        held_reads.append((route, response))
                        return
                    if action == 'docker-container-action' and request['data']['id'] == lose_id[0]:
                        lose_id[0] = None
                        route.abort()
                        return
                    route.fulfill(status=response['status'], json=response['body'], headers=headers)
                    return
                name = 'index.html' if path == '/' else path.removeprefix('/static/')
                if name not in ('index.html', 'app.js', 'network.js', 'style.css', 'icon.svg'):
                    route.fulfill(status=404, body='')
                    return
                route.fulfill(path=str(ROOT / name), headers=headers,
                    content_type='text/html' if name.endswith('html') else
                    'text/javascript' if name.endswith('js') else
                    'text/css' if name.endswith('css') else 'image/svg+xml')

            context.route('**/*', serve)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: csp_errors.append(message.text)
                    if message.type == 'error' and 'Content Security Policy' in message.text else None)
            page.goto('http://192.168.50.24:8765/')
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            page.evaluate('()=>navigate("apps")')
            page.wait_for_function('()=>!routeLoading&&lastLoadedRoute==="apps"')

            def card(identity=ERUGO):
                return page.locator('article.docker-container[data-container-id="' + identity + '"]')

            def button(action, identity=ERUGO):
                return card(identity).locator('[data-action="docker-' + action + '"]')

            def result(identity=ERUGO):
                return card(identity).locator('[data-docker-control-status]')

            def runtime(identity=ERUGO):
                return card(identity).locator('.docker-live-state')

            def collapse(identity=ERUGO):
                return card(identity).locator('[data-action="docker-collapse"]')

            def writes(identity=None):
                return [c for c in traffic if c[0] == 'POST' and c[1] == 'docker-container-action'
                        and (identity is None or c[2]['id'] == identity)]

            def idle():
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&!dockerPage.loading&&!dockerPage.reading')
                expect(card().locator('[aria-busy="true"]')).to_have_count(0)

            def refresh():
                page.locator('[data-action="applications-refresh"]').tap()
                idle()

            def confirm():
                dialog = page.locator('#modal-root [role="dialog"]')
                expect(dialog).to_be_visible()
                dialog.locator('[data-action="confirmed-action"]').tap()

            def dismiss_if_needed():
                if page.locator('#modal-root [role="dialog"]').count():
                    page.locator('#modal-root [data-action="close-modal"]').first.tap()

            def no_overflow():
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width

            # Manual actions are not blocked by monitoring or image preferences.
            expect(button('start')).to_be_enabled()
            expect(runtime()).to_contain_text('Stopped')
            expect(button('stop', OTHER)).to_be_enabled()
            assert api.monitor['legacy'] and not api.monitor['drive-b']
            for control in (button('start'), button('stop', OTHER), button('restart', OTHER)):
                assert control.bounding_box()['height'] >= 48
            initial_settings = copy.deepcopy(api.docker_settings)
            checkbox = card().locator('[data-change="docker-image"][value="' + SECOND_IMAGE + '"]')
            checkbox.check()
            expect(card().locator('[data-action="docker-save"]')).to_be_enabled()
            button('start').tap()
            expect(runtime()).to_contain_text('Running')
            expect(result()).to_contain_text('started')
            expect(button('stop')).to_be_enabled()
            expect(button('restart')).to_be_enabled()
            expect(checkbox).to_be_checked()
            assert api.docker_settings == initial_settings
            assert api.monitor['legacy'] and not api.monitor['drive-b']
            if width in (390, 1440):
                page.screenshot(path=str(shots / ('docker-controls-running-' + str(width) + '.png')), full_page=True)

            # Stop cancellation sends nothing; confirmed stop changes only this container.
            before = len(writes())
            button('stop').tap()
            page.locator('#modal-root [data-action="close-modal"]').first.tap()
            assert len(writes()) == before
            expect(runtime()).to_contain_text('Running')
            button('stop').tap(); confirm()
            expect(runtime()).to_contain_text('Stopped')
            expect(result()).to_contain_text('stopped')
            expect(button('start')).to_be_enabled()
            expect(runtime(OTHER)).to_contain_text('Running')

            # All monitors can be off. A pending start disables only its card's runtime controls.
            api.monitor = {key: False for key in api.monitor}
            page.evaluate('()=>{state.drives.forEach(d=>d.monitoring=false);render()}')
            hold_id[0] = ERUGO
            before = len(writes(ERUGO))
            button('start').tap()
            expect(result()).to_contain_text(re.compile('Starting|starting'))
            expect(button('start')).to_be_disabled()
            button('start').evaluate('(b)=>b.click()')
            assert len(writes(ERUGO)) == before + 1
            expect(button('stop', OTHER)).to_be_enabled()
            # Collapse and restore while pending; progress and dirty settings survive.
            collapse().tap(); expect(collapse()).to_have_attribute('aria-expanded', 'false')
            collapse().tap(); expect(button('start')).to_be_disabled()
            expect(checkbox).to_be_checked()
            # A separate pending storage operation also does not gate Docker controls.
            page.evaluate('()=>{apiBusy=true}')
            button('stop', OTHER).tap(); confirm()
            expect(runtime(OTHER)).to_contain_text('Stopped')
            page.evaluate('()=>{apiBusy=false}')
            hold_id[0] = None
            pending_route, request = held.pop(0)
            response = api.reply(request)
            pending_route.fulfill(status=response['status'], json=response['body'], headers=headers)
            expect(runtime()).to_contain_text('Running')
            expect(result()).to_contain_text('started')
            expect(checkbox).to_be_checked()
            assert all(not value for value in api.monitor.values())
            assert api.docker_settings == initial_settings

            # Restart is explicit and has local feedback after the confirmation disappears.
            before = len(writes())
            button('restart').tap(); confirm()
            expect(result()).to_contain_text('restarted')
            expect(runtime()).to_contain_text('Running')
            assert len(writes()) == before + 1
            assert writes()[-1][2]['action'] == 'restart'

            # Refused Docker requests remain errors and do not falsely say Completed.
            api.control_mode = 'refused'
            button('restart').tap(); confirm()
            expect(result()).to_contain_text('refused')
            expect(result()).to_have_class(re.compile('error'))
            dismiss_if_needed()
            expect(button('restart')).to_be_enabled()
            api.control_mode = ''

            # An accepted request with lost receipt is never replayed automatically.
            before = len(writes())
            lose_id[0] = ERUGO
            button('restart').tap(); confirm()
            expect(result()).to_contain_text(re.compile('not confirmed|unconfirmed|unknown', re.I))
            idle()
            assert len(writes()) == before + 1
            dismiss_if_needed()
            expect(button('restart')).to_be_enabled()

            # A server failure after Docker accepted the operation has the same unknown outcome.
            api.control_mode = 'server-error'
            before = len(writes())
            button('restart').tap(); confirm()
            expect(result()).to_contain_text(re.compile('not confirmed|unconfirmed|unknown', re.I))
            idle()
            assert len(writes()) == before + 1
            dismiss_if_needed(); api.control_mode = ''

            # A normal API reply can also report an unconfirmed runtime result.
            api.control_mode = 'uncertain'
            button('restart').tap(); confirm()
            expect(result()).to_contain_text('not confirmed')
            expect(result()).to_have_class(re.compile('error'))
            dismiss_if_needed(); api.control_mode = ''

            # The exact live identity is checked again by the backend before a mutation.
            replaced = api.container(ERUGO)
            replaced['id'] = 'c' * 64
            before_actions = api.action_counts[ERUGO]
            button('restart').tap(); confirm()
            expect(result()).to_contain_text('identity changed')
            assert api.action_counts[ERUGO] == before_actions
            assert writes()[-1][2]['id'] == ERUGO
            dismiss_if_needed(); replaced['id'] = ERUGO; refresh()

            # An older background read cannot overwrite the action's verified new runtime state.
            api.container(ERUGO)['state'] = 'stopped'; refresh()
            hold_read[0] = True
            page.evaluate('()=>{loadApplications({background:true})}')
            page.wait_for_function('()=>dockerPage.reading')
            button('start').tap()
            expect(runtime()).to_contain_text('Running')
            pending_route, response = held_reads.pop(0)
            pending_route.fulfill(status=response['status'], json=response['body'], headers=headers)
            idle()
            expect(runtime()).to_contain_text('Running')
            expect(checkbox).to_be_checked()

            # No configured drives or detected bind folder is required for manual operation.
            api.docker_drives = []; api.docker_settings = []
            api.container(OTHER)['detected_storage'] = []; api.container(OTHER)['warnings'] = []
            refresh()
            expect(button('start', OTHER)).to_be_enabled()
            button('start', OTHER).tap()
            expect(runtime(OTHER)).to_contain_text('Running')
            expect(result(OTHER)).to_contain_text('started')

            # Paused/dead/transitional/missing cards offer no enabled runtime action.
            for state in ('paused', 'dead', 'restarting', 'unknown'):
                api.container(OTHER)['state'] = state; refresh()
                controls = card(OTHER).locator('[data-action="docker-start"], [data-action="docker-stop"], [data-action="docker-restart"]')
                for index in range(controls.count()):
                    expect(controls.nth(index)).to_be_disabled()
            api.container(OTHER).update(state='missing', discovered=False); refresh()
            controls = card(OTHER).locator('[data-action="docker-start"], [data-action="docker-stop"], [data-action="docker-restart"]')
            for index in range(controls.count()):
                expect(controls.nth(index)).to_be_disabled()
            no_overflow()

            # Manual control never changes restart settings, drive monitoring or image mounting.
            forbidden = {'docker-container-settings', 'monitor', 'image-action', 'disk-operation'}
            assert not any(method == 'POST' and action in forbidden for method, action, _ in traffic)
            assert not errors, errors
            assert not csp_errors, csp_errors
            if width in (390, 1440):
                page.screenshot(path=str(shots / ('docker-controls-' + str(width) + '.png')), full_page=True)
            print('PASS UI18 browser ' + str(width) + 'px: manual Start/Stop/Restart, local outcomes, '
                  'monitoring/storage independence, no duplicate writes, lost responses, draft/collapse '
                  'preservation, stale reads, identity refusal, touch targets and production CSP', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
