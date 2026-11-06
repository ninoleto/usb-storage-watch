# SPDX-License-Identifier: MIT
"""UI15 restart configuration through touch controls and production CSP.

Docker and storage API responses are synthetic. This verifies the actual UI;
backend incident ordering and restart commands are exercised separately.
"""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from test_ui11_browser import API as PreviousAPI, ROOT
from test_ui13_browser import CSP


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.bind = '/mnt/legacy/backup/erugo-storage'
        self.states = {}
        self.rows = [
            dict(id='a'*64, name='test-erugo', running=True, eligible=True, reason='',
                 required_storage=['Test HDD', 'image: backup'], binds=[
                     dict(source=self.bind, destination='/storage', eligible=True, reason='')]),
            dict(id='c'*64, name='direct-uploader', running=True, eligible=True, reason='',
                 required_storage=['Test HDD'], binds=[
                     dict(source='/mnt/legacy/uploads', destination='/uploads', eligible=True, reason='')]),
            dict(id='d'*64, name='multi-storage', running=True, eligible=True, reason='',
                 required_storage=['Test HDD', 'image: backup'], binds=[
                     dict(source='/mnt/legacy/multi', destination='/data', eligible=True, reason=''),
                     dict(source='/mnt/legacy/backup/multi', destination='/backup', eligible=True, reason='')]),
            dict(id='b'*64, name='unrelated', running=True, eligible=False,
                 reason='No writable folder on this drive.', required_storage=[], binds=[]),
        ]

    def reply(self, req):
        parts = urlsplit(req['url']).path.split('/api/', 1)[-1].split('/')
        drive = parts[1] if parts[0] == 'drives' else None
        action = parts[-1]
        data = req.get('data') or {}
        def reply(body, status=200):
            self.calls.append((req['method'], drive, action, data))
            return dict(status=status, body=body)
        if self.session and action == 'application-settings':
            if self.monitor[drive]: return reply(dict(error='Stop monitoring first'), 409)
            if data['revision'] != 'r'+str(self.revisions[drive]):
                return reply(dict(error='Settings changed'), 409)
            if self.fail_save: return reply(dict(error='Synthetic Docker save refusal'), 409)
            c = self.configs[drive]['docker']
            if 'containers' in data:
                selections = []
                for chosen in data['containers']:
                    row = next(x for x in self.rows if x['id'] == chosen['id'])
                    bind = next(x for x in row['binds'] if x['destination'] == chosen['destination'])
                    selections.append(dict(name=row['name'], source=bind['source'],
                                           destination=bind['destination'], grace=30))
                if data['enabled'] and not selections:
                    return reply(dict(error='Select a container first'), 409)
                c['containers'] = selections
            c['enabled'] = data['enabled']
            self.revisions[drive] += 1
            return reply(dict(message='Restart settings saved.', revision='r'+str(self.revisions[drive])))
        if self.session and action == 'application-status' and not self.docker_absent:
            c = self.configs.get(drive, {}).get('docker', {})
            rows = []
            for selected in c.get('containers', []):
                row = next(x for x in self.rows if x['name'] == selected['name'])
                rows.append(dict(**selected, state=self.states.get(row['name'], 'running'),
                    required_storage=row['required_storage'], health=None,
                    recovery=dict(status='preserved_stopped', reason='Stopped before the outage; left stopped.')
                    if self.states.get(row['name']) == 'stopped' else {}))
            return reply(dict(enabled=c.get('enabled', False),
                service=dict(ActiveState='active' if self.monitor[drive] else 'inactive'),
                observed_at='2026-11-02T00:00:00Z', containers=rows))
        return super().reply(req)


def run():
    shots = Path(os.environ.get('USW_UI15_SCREENSHOTS', '/tmp/usw-ui15-shots'))
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API()
            errors, csp_errors, held, held_status = [], [], [], []
            hold_save, lose_save = [False], [False]
            hold_status = [False]
            context = browser.new_context(has_touch=True, viewport=dict(width=width, height=1000))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store',
                       'X-Content-Type-Options': 'nosniff'}
            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if path.startswith('/api/'):
                    req = dict(url=request.url, method=request.method,
                               data=request.post_data_json if request.method == 'POST' else None)
                    if path.endswith('/application-settings') and hold_save[0]:
                        held.append((route, req)); return
                    response = api.reply(req)
                    if path.endswith('/application-status') and hold_status[0]:
                        hold_status[0] = False
                        held_status.append((route, response))
                        page.evaluate('()=>window.staleStatusHeld=true')
                        return
                    if path.endswith('/application-settings') and lose_save[0]:
                        lose_save[0] = False; route.abort(); return
                    route.fulfill(status=response['status'], json=response['body'], headers=headers)
                    return
                name = 'index.html' if path == '/' else path.removeprefix('/static/')
                if name not in ('index.html', 'app.js', 'network.js', 'style.css', 'icon.svg'):
                    route.fulfill(status=404, body=''); return
                route.fulfill(path=str(ROOT/name), headers=headers,
                    content_type='text/html' if name.endswith('html') else
                    'text/javascript' if name.endswith('js') else
                    'text/css' if name.endswith('css') else 'image/svg+xml')
            context.route('**/*', serve)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: csp_errors.append(m.text)
                if m.type == 'error' and 'Content Security Policy' in m.text else None)
            page.goto('http://192.168.50.24:8765/')
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)
            def idle():
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&!Array.from(applicationViews.values()).some(v=>v.loading)')
            def nav(route):
                if page.locator('[data-action="menu"]').is_visible() and 'open' not in (page.locator('#sidebar').get_attribute('class') or '').split():
                    page.locator('[data-action="menu"]').tap()
                page.locator('[data-action="nav"][data-value="'+route+'"]').tap()
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=route)
                idle()
            def pick(identifier, index):
                page.locator('#'+identifier+'-control').tap()
                dialog = page.locator('dialog.touch-picker')
                dialog.get_by_role('option').nth(index).tap()
                idle()
            def writes():
                return [c for c in api.calls if c[0] == 'POST' and c[2] == 'application-settings']
            # Removal is visually separated, and remains a large touch target.
            idle()
            for card in page.locator('[data-drive-card]').all():
                removal = card.locator('[data-action="remove-drive-review"]')
                remove_box = removal.bounding_box()
                controls = card.locator('.drive-primary-actions').bounding_box()
                assert remove_box['height'] >= 48
                if width <= 390:
                    assert remove_box['y'] >= controls['y'] + controls['height'] + 15, (width, remove_box, controls)
                if width == 1440:
                    assert remove_box['x'] >= controls['x'] + controls['width'] + 24, (width, remove_box, controls)
                    assert abs(remove_box['x'] + remove_box['width'] -
                        (card.locator('.drive-card-actions').bounding_box()['x'] +
                         card.locator('.drive-card-actions').bounding_box()['width'])) <= 2
            if width in (390,1440): page.screenshot(path=str(shots/f'overview-{width}.png'), full_page=True)

            nav('apps')
            selection = page.locator('[data-change="application-selection"]')
            expect(selection.first).to_be_disabled()
            page.locator('[data-action="applications-monitor"]').tap(); idle()
            enabled = page.locator('#application-enabled')
            save = page.locator('[data-action="applications-save"]')
            monitor = page.locator('[data-action="applications-monitor"]')
            expect(page.get_by_text('Restart selected containers after drive recovery', exact=True)).to_be_visible()
            expect(save).to_have_text('Save restart settings')
            enabled.check()
            expect(save).to_be_disabled()
            expect(page.locator('#application-validation')).to_contain_text('Select at least one container')
            expect(monitor).to_be_disabled()
            assert writes() == []
            selection.first.check()
            expect(page.locator('#application-validation')).not_to_contain_text('Select at least one container')
            expect(save).to_be_enabled()
            first = page.locator('.application-choice').nth(0)
            direct = page.locator('.application-choice').nth(1)
            multi = page.locator('.application-choice').nth(2)
            expect(first.locator('.application-dependencies')).to_contain_text('backup')
            expect(direct.locator('.application-dependencies')).to_contain_text('None')
            expect(direct.locator('.application-dependencies')).not_to_contain_text('backup')
            expect(first.locator('select')).to_have_count(0)
            details = first.locator('details.application-storage-details')
            assert details.get_attribute('open') is None
            details.locator('summary').tap()
            expect(details).to_contain_text(api.bind)
            expect(details).to_contain_text('/storage')
            # Detailed mappings remain open while live state updates.
            page.evaluate('()=>refreshApplicationStatus("legacy")'); idle()
            assert details.get_attribute('open') is not None
            expect(page.locator('.application-save-state')).to_contain_text('Unsaved')
            expect(selection.nth(3)).to_be_disabled()
            api.fail_save = True; save.tap(); idle()
            expect(page.locator('#applications-message')).to_contain_text('Save not confirmed')
            expect(selection.first).to_be_checked()
            api.fail_save = False
            hold_save[0] = True; save.tap()
            page.wait_for_function('()=>applicationView("legacy").saving')
            expect(selection.first).to_be_disabled(); expect(save).to_be_disabled()
            expect(page.locator('#applications-message')).to_contain_text('Saving')
            assert len(held) == 1
            route, req = held.pop(); hold_save[0] = False
            response = api.reply(req)
            route.fulfill(status=response['status'], json=response['body'], headers=headers)
            idle(); expect(save).to_be_disabled()
            expect(page.locator('#application-live')).to_contain_text('Restart after recovery: On')
            expect(monitor).to_be_enabled()
            assert api.configs['legacy']['docker']['containers'][0]['source'] == api.bind
            # All dependencies survive selecting a different access-check folder.
            selection.nth(2).check()
            multi.locator('details.application-storage-details > summary').tap()
            pick('application-bind-2', 1)
            expect(multi.locator('.application-dependencies')).to_contain_text('backup')
            pick('application-bind-2', 0)
            expect(multi.locator('.application-dependencies')).to_contain_text('backup')
            selection.nth(1).check()
            save.tap(); idle()
            assert len(api.configs['legacy']['docker']['containers']) == 3
            expect(page.locator('#application-live')).to_contain_text('direct-uploader')
            # Missing runtime evidence is Unknown, never a false Stopped report.
            api.states['test-erugo'] = None
            page.evaluate('()=>refreshApplicationStatus("legacy")'); idle()
            live_erugo = page.locator('#application-live article').filter(has=page.get_by_role('heading', name='test-erugo', exact=True))
            expect(live_erugo).to_contain_text('Unknown')
            expect(live_erugo).not_to_contain_text('Stopped')
            # Stopped containers are described as kept stopped, not recovered/restarted.
            api.states['test-erugo'] = 'stopped'
            page.evaluate('()=>refreshApplicationStatus("legacy")'); idle()
            expect(page.locator('#application-live')).to_contain_text('Kept stopped')
            expect(page.locator('#application-live')).to_contain_text('Stopped before the outage')
            if width in (390,1440): page.screenshot(path=str(shots/f'docker-restart-{width}.png'), full_page=True)
            # A pre-save status poll cannot restore the old enabled badge after
            # newer configuration/status has confirmed the settings write.
            hold_status[0] = True
            page.evaluate('()=>{void refreshApplicationStatus("legacy").finally(()=>window.staleStatusDone=true)}')
            page.wait_for_function('()=>window.staleStatusHeld===true')
            enabled.uncheck(); save.tap(); idle()
            expect(page.locator('#application-live')).to_contain_text('Restart after recovery: Off')
            route, response = held_status.pop()
            route.fulfill(status=response['status'], json=response['body'], headers=headers)
            page.wait_for_function('()=>window.staleStatusDone===true')
            expect(page.locator('#application-live')).to_contain_text('Restart after recovery: Off')
            expect(enabled).not_to_be_checked()
            # Losing a settings response after commit is resolved by reading
            # configuration, never automatically repeating the mutation.
            before = len(writes())
            lose_save[0] = True
            enabled.check(); save.tap(); idle()
            assert len(writes()) == before + 1
            assert api.configs['legacy']['docker']['enabled']
            expect(save).to_be_disabled()
            expect(page.locator('#applications-message')).not_to_contain_text('Save not confirmed')
            expect(page.locator('#application-live')).to_contain_text('Restart after recovery: On')
            # The same stale-response guard covers explicit monitoring changes.
            hold_status[0] = True
            page.evaluate('()=>{window.staleStatusHeld=false;window.staleStatusDone=false;void refreshApplicationStatus("legacy").finally(()=>window.staleStatusDone=true)}')
            page.wait_for_function('()=>window.staleStatusHeld===true')
            monitor.tap(); idle()
            assert api.monitor['legacy'] is True
            expect(selection.first).to_be_disabled()
            route, response = held_status.pop()
            route.fulfill(status=response['status'], json=response['body'], headers=headers)
            page.wait_for_function('()=>window.staleStatusDone===true')
            expect(selection.first).to_be_disabled()
            expect(page.locator('#application-live')).to_contain_text('Drive monitoring on')
            expect(monitor).to_have_text('Stop monitoring')
            monitor.tap(); idle()
            assert api.monitor['legacy'] is False
            # A saved restart policy may be disabled even if Docker discovery fails.
            api.docker_absent = True
            page.locator('[data-action="applications-refresh"]').tap(); idle()
            expect(page.locator('.apps-discovery-error')).to_be_visible()
            enabled.uncheck(); expect(save).to_be_enabled(); save.tap(); idle()
            assert not api.configs['legacy']['docker']['enabled']
            assert len(api.configs['legacy']['docker']['containers']) == 3
            assert 'containers' not in writes()[-1][3]
            assert not any(c[2] in ('disk-operation', 'image-action', 'prepare-drive') for c in api.calls)
            assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width
            assert not errors, errors
            assert not csp_errors, csp_errors
            print(f'PASS UI15 {width}px: separated removal, restart wording/requirements, singleton details, multi-bind checks, empty validation, failed/busy saves, stopped state, stale poll protection, lost receipt without replay and offline disable under CSP', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__': run()
