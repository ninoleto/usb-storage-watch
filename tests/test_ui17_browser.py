# SPDX-License-Identifier: MIT
"""UI17 action feedback and image workflows in a real Chromium browser.

Production static files and CSP are used. All host/API responses are synthetic;
these tests never mount a filesystem, start a container, or operate host services.
"""
import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect
from test_ui16_browser import API as PreviousAPI, ROOT, IMAGE, SECOND_IMAGE
from test_ui13_browser import CSP


class API(PreviousAPI):
    def __init__(self):
        super().__init__()
        self.images = [self.image('backup', IMAGE, True),
                       self.image('projects', SECOND_IMAGE, False)]
        self.image_error = ''
        self.read_images_error = ''
        self.create_result = 'success'
        self.reviewed = None
        self.created = 0
        self.disk_error = ''

    @staticmethod
    def image(name, uuid, mounted):
        return dict(name=name, uuid=uuid, size=1024**3,
                    mount_state='mounted' if mounted else 'unmounted',
                    mounted=mounted, enabled=True,
                    image='/mnt/legacy/images/' + name + '.img',
                    mountpoint='/mnt/legacy/' + name,
                    access_message='Available to the local account.' if mounted else 'Not mounted.')

    def reply(self, req):
        parts = urlsplit(req['url']).path.split('/api/', 1)[1].split('/')
        action = parts[-1]
        drive = parts[1] if parts[0] == 'drives' else None
        data = req.get('data') or {}

        def result(body, status=200):
            self.calls.append((req['method'], drive, action, copy.deepcopy(data)))
            return dict(status=status, body=copy.deepcopy(body))

        if self.session:
            if action == 'application-images':
                if self.read_images_error:
                    return result(dict(error=self.read_images_error), 503)
                return result(dict(images=self.images if drive == 'legacy' else []))
            if action == 'image-plan':
                self.reviewed = copy.deepcopy(data)
                return result(dict(token='review-image-' + str(self.created),
                                   message='Create and format only this new image file. Existing files stay unchanged.'))
            if action == 'image-apply':
                if self.create_result == 'refused':
                    return result(dict(error='Synthetic image creation was refused before making changes.'), 409)
                self.created += 1
                item = self.image(self.reviewed['name'], 'created-image-' + str(self.created),
                                  self.create_result in ('success', 'server-error'))
                registered = self.create_result != 'unregistered'
                if registered:
                    self.images.append(item)
                if self.create_result == 'server-error':
                    return result(dict(error='Synthetic server error after image creation.'), 503)
                if self.create_result != 'success':
                    return result(dict(ok=False, changed=True, image_created=True,
                        registered=registered, image=item,
                        message='The image file was created. Mounting could not be completed. '
                                'The file and its contents have been kept. Do not create it again.',
                        images=self.images))
                return result(dict(message='Virtual Disk Image saved, mounted and verified.',
                                   images=self.images))
            if action == 'image-action':
                if self.image_error:
                    return result(dict(error=self.image_error), 409)
                item = next(x for x in self.images if x['uuid'] == data['uuid'])
                operation = data['action']
                if operation == 'set-recovery':
                    item['enabled'] = data['enabled']
                    return result(dict(message='Mount on recovery saved. Current mount unchanged.'))
                if operation == 'remove':
                    self.images.remove(item)
                    return result(dict(message='Registration removed. The image file and its contents were kept.'))
                item['mounted'] = operation == 'mount'
                item['mount_state'] = 'mounted' if item['mounted'] else 'unmounted'
                item['access_message'] = 'Available to the local account.' if item['mounted'] else 'Not mounted.'
                return result(dict(message=('Image mounted and verified.' if item['mounted'] else
                                            'Image safely unmounted.')))
            if action == 'disk-operation' and data.get('action') in ('mount', 'unmount'):
                good = not self.disk_error
                if good:
                    self.mounted[drive] = data['action'] == 'mount'
                self.last = dict(uuid=self.drives[drive][1], action=data['action'], ok=good,
                                 message=self.disk_error or 'Drive operation verified.',
                                 time='2026-11-02T01:30:00Z')
                return result(dict(ok=good, message=self.last['message'], last_operation=self.last))
        return super().reply(req)


def run():
    shots = Path(os.environ.get('USW_UI17_SCREENSHOTS', '/tmp/usw-ui17-shots'))
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('USW_CHROMIUM', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width in (320, 390, 768, 1440):
            api = API()
            errors, csp_errors, held, traffic = [], [], [], []
            hold, lose = [None], [None]
            context = browser.new_context(has_touch=True, viewport=dict(width=width, height=950))
            headers = {'Content-Security-Policy': CSP, 'Cache-Control': 'no-store',
                       'X-Content-Type-Options': 'nosniff'}

            def match(selector, action, request):
                return selector and selector[0] == action and (
                    len(selector) == 1 or (request.get('data') or {}).get('action') == selector[1])

            def serve(route):
                req = route.request
                path = urlsplit(req.url).path
                if path.startswith('/api/'):
                    request = dict(url=req.url, method=req.method,
                                   data=req.post_data_json if req.method == 'POST' else None)
                    action = path.rsplit('/', 1)[-1]
                    traffic.append((req.method, action, copy.deepcopy(request['data'])))
                    if match(hold[0], action, request):
                        held.append((route, request))
                        return
                    response = api.reply(request)
                    if match(lose[0], action, request):
                        lose[0] = None
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

            def idle():
                page.wait_for_function('()=>!apiBusy&&!routeLoading&&!preferencesSaving&&!imagePreferences.size')

            def nav(destination):
                page.evaluate('(r)=>navigate(r)', destination)
                page.wait_for_function('(r)=>!apiBusy&&!routeLoading&&lastLoadedRoute===r', arg=destination)

            def button(action, name=None):
                suffix = '[data-value="' + name + '"]' if name else ''
                return page.locator('[data-action="' + action + '"]' + suffix)

            def feedback(control):
                return control.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " action-control ")][1]').locator('[data-action-status]')

            def writes(action, kind=None):
                return [c for c in api.calls if c[0] == 'POST' and c[2] == action
                        and (kind is None or c[3].get('action') == kind)]

            def release():
                hold[0] = None
                assert held, 'No pending API request was captured'
                route, request = held.pop(0)
                response = api.reply(request)
                route.fulfill(status=response['status'], json=response['body'], headers=headers)

            def feedback_below(control):
                box, status_box = control.bounding_box(), feedback(control).bounding_box()
                assert box and status_box
                assert status_box['y'] >= box['y'] + box['height'] - 1, (box, status_box)

            def no_overflow():
                assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'), width

            # Every asynchronous clicked action has local feedback. Pending state
            # must be visible before the response arrives and cannot be duplicated.
            refresh = button('refresh-drives')
            hold[0] = ('fleet-status',)
            refresh.tap()
            expect(feedback(refresh)).to_contain_text(re.compile('refresh|load|working', re.I))
            expect(refresh).to_be_disabled()
            feedback_below(refresh)
            page.evaluate('()=>render()')
            expect(refresh).to_be_disabled()
            expect(feedback(refresh)).to_contain_text(re.compile('refresh|load|working', re.I))
            page.evaluate('()=>document.querySelector("[data-action=refresh-drives]").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
            page.wait_for_function('()=>apiBusy')
            assert len(held) == 1
            release(); idle()
            expect(feedback(refresh)).to_contain_text(re.compile('refreshed|updated', re.I))
            no_overflow()

            nav('images')
            mount = button('image-toggle-mount', 'projects')
            hold[0] = ('image-action', 'mount')
            mount.tap()
            expect(feedback(mount)).to_contain_text(re.compile('mount|working', re.I))
            expect(mount).to_be_disabled()
            feedback_below(mount)
            page.evaluate('()=>render()')
            expect(mount).to_be_disabled()
            page.evaluate('()=>document.querySelector("[data-action=image-toggle-mount][data-value=projects]").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
            assert len(held) == 1
            release(); idle()
            expect(mount).to_have_text('Unmount image')
            expect(feedback(mount)).to_contain_text('mounted')
            assert len(writes('image-action', 'mount')) == 1
            page.evaluate('()=>render()')
            expect(feedback(mount)).to_contain_text('mounted')
            projects_copy_x = button('copy-image-folder', 'projects').bounding_box()['x']

            # Host refusal is explained under the affected image's button. It
            # neither blocks another image nor silently becomes a success message.
            api.image_error = 'Filesystem has active users (process 12345).'
            before = len(writes('image-action', 'unmount'))
            mount.tap(); idle()
            expect(feedback(mount)).to_contain_text('active users')
            feedback_below(mount)
            expect(feedback(mount)).to_have_class(re.compile('error'))
            assert abs(button('copy-image-folder', 'projects').bounding_box()['x'] - projects_copy_x) < 2, (width, projects_copy_x, button('copy-image-folder', 'projects').bounding_box())
            expect(mount).to_be_enabled()
            assert len(writes('image-action', 'unmount')) == before + 1
            page.evaluate('()=>pollLive()')
            expect(feedback(mount)).to_contain_text('active users')
            api.image_error = ''
            backup = button('image-toggle-mount', 'backup')
            backup.tap(); idle()
            expect(backup).to_have_text('Mount image')
            expect(feedback(backup)).to_contain_text('unmounted')
            expect(feedback(mount)).to_contain_text('active users')
            backup.tap(); idle()
            expect(backup).to_have_text('Unmount image')

            # A settings save has its own pending indicator. Clicking mount while
            # it is pending explains the conflict locally and issues no mount POST.
            pref = page.locator('[data-toggle="image-recovery"][data-key="' + IMAGE + '"]')
            hold[0] = ('image-action', 'set-recovery')
            pref.uncheck()
            expect(pref.locator('xpath=..').locator('.preference-status')).to_contain_text('Saving')
            page.wait_for_function('()=>preferencesSaving')
            before = len(writes('image-action', 'unmount'))
            mount.tap()
            expect(feedback(mount)).to_contain_text(re.compile('saving|pending|wait|operation', re.I))
            assert len(writes('image-action', 'unmount')) == before
            release(); idle()
            mount.tap(); idle()
            expect(mount).to_have_text('Mount image')
            assert len(writes('image-action', 'unmount')) == before + 1
            expect(pref).not_to_be_checked()

            copy_button = button('copy-image-folder', 'backup')
            copy_button.tap()
            expect(feedback(copy_button)).to_contain_text(re.compile('copied|copy', re.I))

            # Lost write response: read-back may display current mounted state,
            # but the write must not be repeated or claimed verified from transport.
            before = len(writes('image-action', 'mount'))
            lose[0] = ('image-action', 'mount')
            mount.tap(); idle()
            expect(feedback(mount)).to_contain_text(re.compile('unconfirm|not confirmed|lost|verify|check|response', re.I))
            assert len(writes('image-action', 'mount')) == before + 1
            expect(mount).to_be_enabled()
            page.evaluate('()=>render()')
            expect(feedback(mount)).to_contain_text(re.compile('unconfirm|not confirmed|lost|verify|check|response', re.I))
            no_overflow()
            if width in (390, 1440):
                page.screenshot(path=str(shots / f'images-feedback-{width}.png'), full_page=True)

            # Normal completion and partial completion both consume the review.
            # A partial operation must explain retained files rather than expose
            # the old Confirm button and tempt a duplicate creation attempt.
            for outcome, name in (('success', 'new-backup'), ('partial', 'partial-backup'),
                                  ('unregistered', 'retained-file')):
                api.create_result = outcome
                button('image-tab', 'create').tap()
                page.locator('#new-image-name').fill(name)
                page.locator('#new-image-capacity').fill('1')
                review = page.locator('[data-form="image-create"] button[type="submit"]')
                review.tap()
                expect(page.get_by_role('dialog')).to_contain_text('Create virtual disk image?')
                expect(feedback(button('confirmed-action'))).to_have_text('')
                hold[0] = ('image-apply',)
                confirm = button('confirmed-action')
                before = len(writes('image-apply'))
                confirm.tap()
                expect(confirm).to_be_disabled()
                expect(page.locator('#modal-root')).to_contain_text(re.compile('creating|working|waiting|submitted', re.I))
                page.evaluate('()=>document.querySelector("[data-action=confirmed-action]").dispatchEvent(new MouseEvent("click",{bubbles:true}))')
                assert len(held) == 1
                release(); idle()
                expect(page.locator('#modal-root .modal')).to_have_count(0)
                assert len(writes('image-apply')) == before + 1
                result = page.locator('[data-image-result]')
                expect(result).to_be_visible()
                expect(result).to_contain_text('mounted and verified' if outcome == 'success' else 'created')
                if outcome != 'success':
                    expect(result).to_contain_text('Do not create it again')
                page.evaluate('()=>render()')
                expect(result).to_be_visible()
                no_overflow()

            # A definite refusal is visible inside the open confirmation dialog,
            # not solely in the distant Messages history; pending state releases.
            api.create_result = 'refused'
            button('image-tab', 'create').tap()
            page.locator('#new-image-name').fill('refused-backup')
            page.locator('[data-form="image-create"] button[type="submit"]').tap()
            button('confirmed-action').tap(); idle()
            expect(page.get_by_role('dialog')).to_contain_text('Synthetic image creation was refused')
            expect(button('confirmed-action')).to_be_disabled()
            button('close-modal').tap()

            # An accepted creation whose receipt disappears must never leave
            # an enabled Confirm that can resubmit its consumed review token.
            api.create_result = 'success'
            button('image-tab', 'create').tap()
            page.locator('#new-image-name').fill('receipt-lost-backup')
            page.locator('[data-form="image-create"] button[type="submit"]').tap()
            expect(feedback(button('confirmed-action'))).to_have_text('')
            before = len(writes('image-apply'))
            lose[0] = ('image-apply',)
            button('confirmed-action').tap(); idle()
            assert len(writes('image-apply')) == before + 1
            expect(page.locator('[data-action="confirmed-action"]:enabled')).to_have_count(0)
            expect(page.locator('[data-image-result]')).to_contain_text(
                re.compile('unconfirm|not confirmed|lost|verify|check|response', re.I))
            assert any(x['name'] == 'receipt-lost-backup' for x in api.images)
            if page.locator('#modal-root .modal').count():
                button('close-modal').tap()

            # HTTP 5xx after mutation is also an uncertain outcome. The request
            # may have created the image before its server-side error response.
            api.create_result = 'server-error'
            button('image-tab', 'create').tap()
            page.locator('#new-image-name').fill('server-error-backup')
            page.locator('[data-form="image-create"] button[type="submit"]').tap()
            before = len(writes('image-apply'))
            button('confirmed-action').tap(); idle()
            assert len(writes('image-apply')) == before + 1
            expect(page.locator('[data-action="confirmed-action"]:enabled')).to_have_count(0)
            expect(page.locator('[data-image-result]')).to_contain_text(re.compile('unconfirmed|not confirmed', re.I))
            expect(page.locator('[data-image-result]')).to_contain_text('Synthetic server error')
            assert any(x['name'] == 'server-error-backup' for x in api.images)
            if page.locator('#modal-root .modal').count():
                button('close-modal').tap()

            # A physical-drive host refusal must be placed below its originating
            # button even though the confirmation has already been dismissed.
            nav('drive/legacy')
            api.disk_error = 'Drive is in use by a mounted image or application.'
            disk = button('toggle-mount')
            disk.tap(); button('confirmed-action').tap(); idle()
            if page.locator('#modal-root .modal').count():
                expect(page.get_by_role('dialog')).to_contain_text('Drive is in use')
                button('close-modal').tap()
            expect(feedback(disk)).to_contain_text('Drive is in use')
            expect(feedback(disk)).to_have_class(re.compile('error'))
            expect(disk).to_be_enabled()
            assert len(writes('disk-operation', 'unmount')) == 1

            # Copy URL must await clipboard completion and attach a rejection to
            # its own button instead of producing an unhandled promise rejection.
            nav('advanced')
            page.evaluate('''()=>{
              Object.defineProperty(window,'isSecureContext',{value:true,configurable:true});
              Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('Synthetic clipboard denied');}},configurable:true});
            }''')
            copy_url = button('network-copy').first
            copy_url.tap()
            expect(feedback(copy_url)).to_contain_text(re.compile('copy failed|copy.*manually', re.I))
            expect(feedback(copy_url)).to_have_class(re.compile('error'))

            # Exercise the real AbortController path without waiting the normal
            # host-operation budget: only this request's explicit timeout changes.
            # A hanging write releases the browser lock, stays unconfirmed locally,
            # and is never automatically resubmitted after the timeout.
            if width == 390:
                nav('images')
                hold[0] = ('image-action', 'unmount')
                before = len([r for r in traffic if r[0] == 'POST' and r[1] == 'image-action'])
                page.evaluate('''()=>{
                  window.ui17OriginalApiRequest=apiRequest;
                  apiRequest=(action,options={})=>window.ui17OriginalApiRequest(action,
                    action==='image-action'?{...options,timeout:150}:options);
                }''')
                timeout_button = button('image-toggle-mount', 'backup')
                timeout_button.tap()
                expect(feedback(timeout_button)).to_contain_text(re.compile('mount|working', re.I))
                idle()
                expect(feedback(timeout_button)).to_contain_text(re.compile('not confirmed|unconfirmed', re.I))
                expect(timeout_button).to_be_enabled()
                assert len([r for r in traffic if r[0] == 'POST' and r[1] == 'image-action']) == before + 1
                assert len(held) == 1
                hold[0] = None
                abandoned, _ = held.pop(0)
                abandoned.abort()
                page.evaluate('()=>{apiRequest=window.ui17OriginalApiRequest;delete window.ui17OriginalApiRequest;}')

            # Static shell controls survive session transitions; their previous
            # pending state must not disable Sign out after signing in again.
            if button('menu').is_visible() and 'open' not in (page.locator('#sidebar').get_attribute('class') or '').split():
                button('menu').tap()
            button('sign-out').tap()
            expect(page.locator('#usw-login')).to_be_visible()
            page.locator('#usw-login-token').fill('synthetic-token')
            page.locator('#usw-login-form button').tap()
            expect(page.locator('#usw-app')).to_be_visible()
            idle()
            expect(button('sign-out')).to_be_enabled()
            no_overflow()
            assert not errors, errors
            assert not csp_errors, csp_errors
            print(f'PASS UI17 browser {width}px: local progress/error/success, no duplicate writes, '
                  'preference overlap, lost response, normal/partial image creation, modal feedback and state recovery')
            page.close(); context.close()
        browser.close()


if __name__ == '__main__':
    run()
