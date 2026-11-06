# SPDX-License-Identifier: MIT
"""UI16 container-first Docker settings in Chromium under production CSP.

The complete shipped UI is exercised against synthetic HTTP API responses.
No Docker engine, filesystem mounts, services, or host configuration is changed.
"""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from test_ui11_browser import API as PreviousAPI, ROOT
from test_ui13_browser import CSP


ERUGO = 'a' * 64
OTHER = 'b' * 64
IMAGE = '22222222-2222-4222-8222-222222222222'
SECOND_IMAGE = '33333333-3333-4333-8333-333333333333'


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.docker_revision = 1
        self.docker_reads = 0
        self.docker_error = ''
        self.docker_drives = [
            dict(id='legacy', name='EXAMPLE SATA DISK', size=500107862016,
                 images=[dict(uuid=IMAGE, name='sample-volume', enabled=True),
                         dict(uuid=SECOND_IMAGE, name='backup-image', enabled=False)]),
            dict(id='drive-b', name='TOSHIBA MQ01UBD050', size=500107862016, images=[]),
        ]
        self.containers = [
            dict(id=ERUGO, name='sample-app', state='running', health=None,
                 warnings=['Docker detects storage in sample-volume. Detection is advice only.'],
                 detected_storage=[dict(drive_id='legacy', drive_name='EXAMPLE SATA DISK',
                                        image_uuid=IMAGE, image_name='sample-volume')]),
            dict(id=OTHER, name='independent-uploader', state='stopped', health=None,
                 warnings=[], detected_storage=[]),
        ]
        self.docker_settings = [
            dict(id=ERUGO, name='sample-app', drives=[
                dict(id='legacy', enabled=True, images=[IMAGE]),
                dict(id='drive-b', enabled=False, images=[])]),
            dict(id=OTHER, name='independent-uploader', drives=[
                dict(id='legacy', enabled=False, images=[]),
                dict(id='drive-b', enabled=False, images=[])]),
        ]

    def snapshot(self):
        value = dict(revision='docker-' + str(self.docker_revision),
                     containers=copy.deepcopy(self.containers),
                     drives=copy.deepcopy(self.docker_drives),
                     settings=copy.deepcopy([v for v in self.docker_settings
                                             if any(d['enabled'] for d in v['drives'])]),
                     observed_at='2026-11-02T01:30:00Z')
        if self.docker_error:
            value['error'] = self.docker_error
        return value

    def choice(self, container, drive):
        setting = next(x for x in self.docker_settings if x['id'] == container)
        return next(x for x in setting['drives'] if x['id'] == drive)

    def reply(self, req):
        action = urlsplit(req['url']).path.rsplit('/', 1)[-1]
        data = req.get('data') or {}
        if self.session and action in ('docker-overview', 'docker-container-settings'):
            self.calls.append((req['method'], None, action, copy.deepcopy(data)))
            if action == 'docker-overview':
                self.docker_reads += 1
                return dict(status=200, body=self.snapshot())
            if self.fail_save:
                return dict(status=409, body=dict(error='Synthetic save refusal'))
            if data.get('revision') != 'docker-' + str(self.docker_revision):
                return dict(status=409, body=dict(error='Settings changed. Refresh before saving.'))
            assert set(data) == {'id', 'name', 'revision', 'drives'}, data
            assert {d['id'] for d in data['drives']} == {'legacy', 'drive-b'}
            assert all(type(d['enabled']) is bool and isinstance(d['images'], list) for d in data['drives'])
            target = next(x for x in self.docker_settings if x['id'] == data['id'])
            assert target['name'] == data['name']
            target['drives'] = copy.deepcopy(data['drives'])
            self.docker_revision += 1
            return dict(status=200, body=dict(revision='docker-' + str(self.docker_revision),
                message='Container restart settings saved.',
                settings=copy.deepcopy([v for v in self.docker_settings
                                        if any(d['enabled'] for d in v['drives'])])))
        return super().reply(req)


def run():
    shots = Path(os.environ.get('USW_UI16_SCREENSHOTS', '/tmp/usw-ui16-shots'))
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API()
            errors, csp_errors, held_save, held_read = [], [], [], []
            hold_save, lose_save, hold_read, fail_read = [False], [False], [False], [False]
            context = browser.new_context(has_touch=True, viewport=dict(width=width, height=1000))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store',
                       'X-Content-Type-Options': 'nosniff'}

            def serve(route):
                req = route.request
                path = urlsplit(req.url).path
                if path.startswith('/api/'):
                    request = dict(url=req.url, method=req.method,
                                   data=req.post_data_json if req.method == 'POST' else None)
                    if path.endswith('/docker-overview') and fail_read[0]:
                        route.fulfill(status=503, json=dict(error='Synthetic Docker unavailable'), headers=headers)
                        return
                    if path.endswith('/docker-container-settings') and hold_save[0]:
                        held_save.append((route, request))
                        return
                    reply = api.reply(request)
                    if path.endswith('/docker-overview') and hold_read[0]:
                        hold_read[0] = False
                        held_read.append((route, reply))
                        return
                    if path.endswith('/docker-container-settings') and lose_save[0]:
                        lose_save[0] = False
                        route.abort()
                        return
                    route.fulfill(status=reply['status'], json=reply['body'], headers=headers)
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
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: csp_errors.append(m.text)
                    if m.type == 'error' and 'Content Security Policy' in m.text else None)
            page.goto('http://192.168.50.24:8765/')
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            expect(page.locator('[data-drive-card]')).to_have_count(2)

            def idle():
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&!dockerPage.saving&&!dockerPage.loading')
                expect(page.locator('.docker-save-status').filter(has_text='Saving')).to_have_count(0)

            def nav(route):
                page.evaluate('(r)=>navigate(r)', route)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=route)

            def card(identifier):
                return page.locator('article.docker-container[data-container-id="' + identifier + '"]')

            def drive(identifier, profile):
                return card(identifier).locator('[data-change="docker-drive"][data-drive="' + profile + '"]')

            def image(identifier, image_id=IMAGE):
                return card(identifier).locator('[data-change="docker-image"][value="' + image_id + '"]')

            def save(identifier):
                return card(identifier).locator('[data-action="docker-save"]')

            def collapse(identifier):
                return card(identifier).locator('[data-action="docker-collapse"]')

            def writes():
                return [c for c in api.calls if c[0] == 'POST' and c[2] == 'docker-container-settings']

            def no_overflow():
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width

            nav('apps')
            expect(page.locator('article.docker-container')).to_have_count(2)
            expect(page.locator('#apps-drive')).to_have_count(0)
            expect(page.locator('[data-action="applications-monitor"]')).to_have_count(0)
            expect(page.locator('[data-action="applications-check"]')).to_have_count(0)
            expect(card(ERUGO).locator('.docker-live-state')).to_contain_text('Running')
            expect(card(OTHER).locator('.docker-live-state')).to_contain_text('Stopped')
            for identifier in (ERUGO, OTHER):
                if collapse(identifier).get_attribute('aria-expanded') == 'false':
                    collapse(identifier).tap()
                expect(drive(identifier, 'legacy')).to_be_enabled()
                expect(drive(identifier, 'drive-b')).to_be_enabled()
                expect(save(identifier)).to_be_disabled()
                assert collapse(identifier).bounding_box()['height'] >= 44
            assert api.monitor['legacy'] is True and api.monitor['drive-b'] is False
            expect(image(ERUGO)).to_be_checked()
            expect(image(ERUGO, SECOND_IMAGE)).not_to_be_checked()
            no_overflow()

            # A detected container with no bind to either disk remains selectable.
            drive(OTHER, 'legacy').check()
            expect(save(OTHER)).to_be_enabled()
            expect(card(OTHER).locator('[data-action="docker-image-none"]')).to_be_visible()
            expect(image(OTHER)).not_to_be_checked()
            save(OTHER).tap(); idle()
            expect(save(OTHER)).to_be_disabled()
            assert api.choice(OTHER, 'legacy') == dict(id='legacy', enabled=True, images=[])
            assert api.choice(ERUGO, 'legacy')['images'] == [IMAGE]
            assert api.monitor['legacy'] and not api.monitor['drive-b']

            # Collapse is keyboard/touch accessible and does not erase a draft.
            image(ERUGO, SECOND_IMAGE).check()
            expect(save(ERUGO)).to_be_enabled()
            collapse(ERUGO).focus(); page.keyboard.press('Enter')
            expect(collapse(ERUGO)).to_have_attribute('aria-expanded', 'false')
            expect(card(ERUGO).locator('.docker-container-body')).to_be_hidden()
            expect(card(ERUGO).locator('.docker-live-state')).to_be_visible()
            collapse(ERUGO).tap()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()

            # Another card's successful save must preserve that unsaved selection.
            drive(OTHER, 'drive-b').check()
            save(OTHER).tap(); idle()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            assert api.choice(OTHER, 'drive-b')['enabled'] is True

            api.fail_save = True
            save(ERUGO).tap(); idle()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('not confirmed')
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            api.fail_save = False

            # Editing remains possible during a pending save. Acknowledging the
            # submitted snapshot must not discard changes made afterwards.
            hold_save[0] = True
            save(ERUGO).tap()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('Saving')
            expect(save(ERUGO)).to_be_disabled()
            expect(drive(OTHER, 'drive-b')).to_be_enabled()
            expect(image(ERUGO)).to_be_enabled()
            image(ERUGO).uncheck()
            assert len(held_save) == 1
            held, request = held_save.pop(); hold_save[0] = False
            reply = api.reply(request)
            held.fulfill(status=reply['status'], json=reply['body'], headers=headers)
            idle(); expect(save(ERUGO)).to_be_enabled()
            assert set(api.choice(ERUGO, 'legacy')['images']) == {IMAGE, SECOND_IMAGE}
            expect(image(ERUGO)).not_to_be_checked()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('newer changes')
            save(ERUGO).tap(); idle()
            assert api.choice(ERUGO, 'legacy')['images'] == [SECOND_IMAGE]
            expect(save(ERUGO)).to_be_disabled()

            # Reverting to the old saved baseline while the opposite value is
            # in flight is still a NEW edit; its apparent old-baseline cleanliness
            # must not allow the submitted snapshot to overwrite it.
            image(ERUGO).check()
            hold_save[0] = True
            save(ERUGO).tap()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('Saving')
            image(ERUGO).uncheck()
            assert len(held_save) == 1
            held, request = held_save.pop(); hold_save[0] = False
            reply = api.reply(request)
            held.fulfill(status=reply['status'], json=reply['body'], headers=headers)
            idle()
            expect(image(ERUGO)).not_to_be_checked()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('newer changes')
            save(ERUGO).tap(); idle()
            assert api.choice(ERUGO, 'legacy')['images'] == [SECOND_IMAGE]

            # None explicitly removes image requirements; detection stays advisory.
            card(ERUGO).locator('[data-action="docker-image-none"][data-value="legacy"]').tap()
            expect(image(ERUGO)).not_to_be_checked()
            expect(image(ERUGO, SECOND_IMAGE)).not_to_be_checked()
            expect(drive(ERUGO, 'legacy')).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            before = len(writes()); lose_save[0] = True
            save(ERUGO).tap(); idle()
            expect(save(ERUGO)).to_be_disabled()
            assert len(writes()) == before + 1
            assert api.choice(ERUGO, 'legacy')['images'] == []
            expect(card(ERUGO).locator('.docker-save-status')).not_to_contain_text('not confirmed')

            # Keep an old background response pending across a successful save.
            hold_read[0] = True
            page.evaluate('()=>{void pollLive();}')
            page.wait_for_function('()=>pollPending')
            page.wait_for_timeout(100)
            assert len(held_read) == 1
            image(ERUGO).check()
            save(ERUGO).tap(); idle()
            expect(save(ERUGO)).to_be_disabled()
            held, reply = held_read.pop()
            held.fulfill(status=reply['status'], json=reply['body'], headers=headers)
            page.wait_for_function('()=>!pollPending')
            expect(image(ERUGO)).to_be_checked()
            expect(save(ERUGO)).to_be_disabled()
            assert api.choice(ERUGO, 'legacy')['images'] == [IMAGE]

            # Losing both the POST response and its immediate reconciliation GET
            # is resolved by a later successful refresh, never a second POST.
            before = len(writes())
            image(ERUGO, SECOND_IMAGE).check()
            lose_save[0] = True; fail_read[0] = True
            save(ERUGO).tap(); idle()
            expect(card(ERUGO).locator('.docker-save-status')).to_contain_text('not confirmed')
            expect(save(ERUGO)).to_be_disabled()
            fail_read[0] = False
            page.locator('[data-action="applications-refresh"]').tap(); idle()
            expect(save(ERUGO)).to_be_disabled()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(card(ERUGO).locator('.docker-save-status')).not_to_contain_text('not confirmed')
            assert len(writes()) == before + 1
            image(ERUGO, SECOND_IMAGE).uncheck()
            save(ERUGO).tap(); idle()

            # Poll updates runtime status without erasing unsaved drive choices.
            drive(ERUGO, 'drive-b').check()
            api.containers[0]['state'] = 'unknown'
            page.evaluate('()=>pollLive()')
            expect(card(ERUGO).locator('.docker-live-state')).to_contain_text('Unknown')
            expect(drive(ERUGO, 'drive-b')).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            save(ERUGO).tap(); idle()
            api.containers[0]['state'] = 'running'
            page.evaluate('()=>pollLive()')
            expect(card(ERUGO).locator('.docker-live-state')).to_contain_text('Running')

            # Refresh gives nearby feedback without taking away draft controls.
            hold_read[0] = True
            page.locator('[data-action="applications-refresh"]').tap()
            expect(page.get_by_text('Refreshing containers…', exact=True)).to_be_visible()
            assert len(held_read) == 1
            held, reply = held_read.pop()
            held.fulfill(status=reply['status'], json=reply['body'], headers=headers)
            idle()
            no_overflow()
            if width in (390, 1440):
                page.screenshot(path=str(shots / f'docker-expanded-{width}.png'), full_page=True)

            for identifier in (ERUGO, OTHER):
                collapse(identifier).tap()
                expect(collapse(identifier)).to_have_attribute('aria-expanded', 'false')
                expect(card(identifier).locator('.docker-container-body')).to_be_hidden()
            if width in (390, 1440):
                page.screenshot(path=str(shots / f'docker-collapsed-{width}.png'), full_page=True)
            nav('overview'); nav('apps')
            for identifier in (ERUGO, OTHER):
                expect(collapse(identifier)).to_have_attribute('aria-expanded', 'false')
            page.reload()
            expect(page.locator('article.docker-container')).to_have_count(2)
            for identifier in (ERUGO, OTHER):
                expect(collapse(identifier)).to_have_attribute('aria-expanded', 'false')

            # A refresh failure reports unknown runtime state but preserves both
            # saved selections and unsaved draft values.
            collapse(ERUGO).tap()
            image(ERUGO, SECOND_IMAGE).check()
            fail_read[0] = True
            page.locator('[data-action="applications-refresh"]').tap(); idle()
            expect(page.locator('#docker-page-error')).to_contain_text('Synthetic Docker unavailable')
            expect(card(ERUGO).locator('.docker-live-state')).to_contain_text('Unknown')
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()
            fail_read[0] = False
            page.locator('[data-action="applications-refresh"]').tap(); idle()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(save(ERUGO)).to_be_enabled()

            # Docker can replace a container with the same name. Identity, draft
            # choices and persisted collapse state must not transfer to its new ID.
            collapse(ERUGO).tap()
            replacement = 'c' * 64
            api.containers[0].update(state='missing', discovered=False)
            api.containers.append(dict(id=replacement, name='sample-app', state='running',
                health=None, warnings=[], detected_storage=[]))
            page.locator('[data-action="applications-refresh"]').tap(); idle()
            expect(page.locator('article.docker-container')).to_have_count(3)
            expect(collapse(ERUGO)).to_have_attribute('aria-expanded', 'false')
            expect(collapse(replacement)).to_have_attribute('aria-expanded', 'true')
            expect(drive(replacement, 'legacy')).not_to_be_checked()
            expect(drive(replacement, 'drive-b')).not_to_be_checked()
            expect(card(ERUGO).locator('.docker-live-state')).to_contain_text('Missing')
            collapse(ERUGO).tap()
            expect(image(ERUGO, SECOND_IMAGE)).to_be_checked()
            expect(drive(ERUGO, 'legacy')).to_be_enabled()
            expect(drive(ERUGO, 'drive-b')).to_be_enabled()
            drive(ERUGO, 'legacy').uncheck()
            drive(ERUGO, 'drive-b').uncheck()
            save(ERUGO).tap(); idle()
            assert not any(d['enabled'] for d in next(s for s in api.docker_settings if s['id'] == ERUGO)['drives'])
            expect(drive(replacement, 'legacy')).not_to_be_checked()
            no_overflow()
            assert not any(c[2] in ('disk-operation', 'image-action', 'prepare-drive', 'monitor-control')
                           for c in api.calls if c[0] == 'POST'), api.calls
            assert api.monitor['legacy'] and not api.monitor['drive-b']
            assert not errors, errors
            assert not csp_errors, csp_errors
            print(f'PASS UI16 {width}px: container-first settings, both monitoring states, per-drive image choices, '
                  'cross-card and in-flight drafts, collapse persistence, save failures/lost responses, '
                  'stale polling, failed refresh and replacement identities, '
                  'touch targets, no overflow and production CSP', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
