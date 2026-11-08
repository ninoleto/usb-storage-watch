# SPDX-License-Identifier: MIT
"""Unprivileged Flask frontend. Privileged actions require broker authorization."""
import importlib.util
import io
import json
from pathlib import Path
import ssl
import subprocess
import sys
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('web_common', Path(__file__).with_name('web_common.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
integrations = common.module('web_integrations')

READS = {'drive-activity', 'session', 'status', 'config', 'disks', 'docker', 'events', 'diagnostics', 'mount-plan', 'migration-plan', 'protection-plan', 'unmount-plan'}
READS.update(('application-status', 'docker-overview'))
READS.update(('usb-status','fleet-status'))
READS.update(('global-config','fleet-events','notification-preferences','recovery-plan','image-discover',
              'drive-rebind-candidates','drive-rebind-plan'))
WRITES = {'logout', 'config', 'smtp', 'test-email', 'monitor', 'qualify', 'network', 'validate', 'prepare-mount', 'migrate-mount', 'rollback-mount', 'activate-protection', 'disk-operation', 'standby-settings', 'advanced-recovery', 'protection-settings'}
READS.add('prepare-disks')
WRITES.update(('prepare-drive-plan', 'prepare-drive', 'prepare-drive-activate'))
WRITES.update(('change-mount-location','add-drive'))
WRITES.update(('recovery-settings','notification-settings','drive-rebind-apply'))
READS.update(('login-info','application-images','local-accounts','lan-info','lan-status','prepare-progress'))
WRITES.update(('image-plan','image-apply','image-action','application-settings','timing-settings','lan-auto','folder-access-plan','folder-access-apply','management-token'))
WRITES.update(('application-check', 'docker-container-settings', 'docker-container-action', 'docker-boot-settings'))
WRITES.update(('docker-setup-plan', 'docker-setup-apply', 'docker-permission-plan', 'docker-permission-apply', 'docker-app-plan', 'docker-app-save', 'docker-entry-plan', 'docker-entry-apply'))
READS.add('network-state')
READS.add('remove-drive-plan')
WRITES.add('remove-drive')
WRITES.update(('network-stage','network-confirm','network-cancel','network-certificate','network-renew'))


def create_app(config=None, transport=common.rpc):
    from flask import Flask, request, jsonify, send_from_directory, send_file
    config = common.network_config(config or json.loads(common.WEB_CONFIG.read_text()))
    static = Path(__file__).with_name('web_static')
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=65536)
    hosts = {config['address'],config['hostname']} if config['lan'] else {'localhost','127.0.0.1'}
    scheme = config['scheme'] if config['lan'] else 'http'
    cookie='usw_lan_http' if config['lan'] and scheme=='http' else 'usw_session'
    allowed = {f'{host}:{config["port"]}' for host in hosts}

    @app.before_request
    def protect():
        if request.host not in allowed or request.scheme != scheme:
            return jsonify(error='Unrecognized host or insecure connection.'), 403
        if request.method not in ('GET', 'POST', 'HEAD'):
            return jsonify(error='Method not allowed.'), 405
        if request.method == 'POST':
            if (request.headers.get('Origin') != scheme + '://' + request.host
                    or request.headers.get('X-USW-Request') != '1' or not request.is_json):
                return jsonify(error='Same-origin JSON request required.'), 403

    @app.after_request
    def headers(response):
        response.headers.update({
            'X-USW-Listener': scheme+'://'+config['address']+':'+str(config['port']),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})
        return response

    @app.get('/')
    def index():
        return send_from_directory(static, 'index.html')

    @app.get('/static/<name>')
    def asset(name):
        if name not in ('app.js', 'network.js', 'style.css', 'icon.svg', 'select-arrow.svg'):
            return '', 404
        return send_from_directory(static, name)

    def download_authorization():
        # Reuse dashboard authentication. Bearer tokens are never accepted here.
        try:
            check = transport(dict(action='session', write=False, data={},
                                   token=request.cookies.get(cookie, ''),
                                   local=not config['lan'], secure=scheme=='https', csrf=''))
        except (OSError, ValueError):
            return jsonify(error='Authentication service unavailable.'), 503
        if check.get('status') != 200:
            return jsonify(error='Sign in to access setup downloads.'), 401
        return None

    @app.get('/download/trust-certificate.pem')
    @app.get('/download/proposed-trust-certificate.pem')
    def trust_certificate():
        denied = download_authorization()
        if denied is not None: return denied
        path = common.WEB_DIR / ('proposed-network-ca.pem' if request.path.endswith('/proposed-trust-certificate.pem') else 'local-network-ca.pem')
        try:
            content = integrations.certificate(path).encode('ascii')
        except (OSError, ValueError, UnicodeError):
            return jsonify(error='Public trust certificate is unavailable.'), 404
        return send_file(io.BytesIO(content), mimetype='application/x-pem-file',
                         as_attachment=True, download_name='usb-storage-watch-ca.crt')

    @app.get('/api/integration-info')
    def integration_info():
        denied = download_authorization()
        if denied is not None: return denied
        try:
            module, _ = integrations.module_package()
        except (OSError, ValueError, UnicodeError):
            module = dict(available=False)
        try:
            pem = integrations.certificate(common.WEB_DIR / 'local-network-ca.pem')
        except (OSError, ValueError, UnicodeError):
            pem = None
        return jsonify(module=module, certificate_pem=pem)

    @app.get('/download/companion-module.tgz')
    def companion_module():
        denied = download_authorization()
        if denied is not None: return denied
        try:
            info, content = integrations.module_package()
        except (OSError, ValueError, UnicodeError):
            return jsonify(error='Companion module package is unavailable.'), 404
        return send_file(io.BytesIO(content), mimetype='application/gzip', as_attachment=True,
                         download_name='usb-storage-watch-companion-'+info['version']+'.tgz')

    @app.route('/api/<action>', methods=['GET', 'POST'])
    @app.route('/api/drives/<drive>/<action>', methods=['GET', 'POST'])
    def api(action, drive=None):
        if drive is not None and request.headers.get('X-USW-Drive') not in (None,drive):
            return jsonify(error='Conflicting drive identifiers. Open the intended drive from Overview.'),400
        write = request.method == 'POST'
        if action != 'login' and action not in (WRITES if write else READS):
            return jsonify(error='Unknown action.'), 404
        if action == 'login' and not write:
            return '', 405
        data = request.get_json(silent=True) if write else dict(request.args)
        if not isinstance(data, dict):
            return jsonify(error='Expected an object.'), 400
        try:
            result = transport(dict(action=action, write=write, data=data,
                                    drive=drive or request.headers.get('X-USW-Drive'),token=request.cookies.get(cookie, ''),local=not config['lan'],secure=scheme=='https',
                                    origin=scheme+'://'+request.host,
                                    csrf=request.headers.get('X-CSRF-Token', '')))
        except (OSError, ValueError):
            return jsonify(error='Administration service unavailable. Try again shortly.'), 503
        status = result.get('status', 200)
        body = result.get('data', {}) if status == 200 else {'error': result.get('error', 'Operation failed.')}
        if status != 200:
            body.update({key: result[key] for key in ('field', 'step', 'action') if key in result})
        token = body.pop('token', None) if action == 'login' else None
        response = jsonify(body)
        if token:
            response.set_cookie(cookie, token, httponly=True, secure=scheme=='https',
                                samesite='Strict', max_age=28800, path='/')
        if action == 'logout':
            response.delete_cookie(cookie, path='/', httponly=True, samesite='Strict', secure=scheme=='https')
        return response, status

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error='Request too large.'), 413

    return app


def listener_config(argv):
    if '--network-test' in argv:
        index = argv.index('--network-test')
        role = argv[index+1] if index+1 < len(argv) else ''
        if role not in ('local', 'lan'):
            raise ValueError('Invalid network test listener.')
        return common.network_config(json.loads((common.WEB_DIR/('test-'+role+'.json')).read_text())), 'test-'
    if '--lan' in argv:
        return common.network_config(json.loads(common.WEB_CONFIG.read_text())), ''
    # Local HTTP can start even if optional LAN settings/certificates are invalid.
    try:
        raw = json.loads(common.WEB_CONFIG.read_text())
        port = raw.get('http_port', 8765)
        if type(port) is not int or not 1024 <= port <= 65535: port = 8765
    except (OSError, ValueError, AttributeError):
        port = 8765
    return common.network_config(dict(common.DEFAULT, port=port, http_port=port)), ''


def main():
    # Use the pinned upstream HTTP parser, never an older system Gunicorn.
    sys.path.insert(0, str(Path(__file__).with_name('_vendor')))
    import gunicorn
    if gunicorn.__version__ != '26.2.0':
        raise SystemExit('Expected bundled Gunicorn 26.2.0')
    from gunicorn.app.base import BaseApplication
    # Separate processes: invalid/disabled LAN configuration cannot affect local HTTP.
    config, prefix = listener_config(sys.argv)
    if '--lan' in sys.argv and not config['lan']:
        return
    if config['lan']:
        # A stale address at boot/disconnect is a waiting state, not a crash loop.
        try:
            addresses = common.module('network_addresses')
            selected = addresses.choose(config, addresses.discover())
            if not selected or selected['address'] != config['address']: return
        except (OSError, ValueError, subprocess.SubprocessError):
            return
    def tls_context(_config, _default_factory):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(common.WEB_DIR / (prefix+'certificate.pem'), common.WEB_DIR / (prefix+'key.pem'))
        return context
    class Server(BaseApplication):
        def load_config(self):
            binds = [f'{config["address"]}:{config["port"]}'] if config['lan'] else [f'127.0.0.1:{config["port"]}']
            options = dict(bind=binds, workers=1, worker_class='gthread', threads=4,
                           timeout=60, accesslog=None, errorlog='-', loglevel='warning',
                           limit_request_line=2048, limit_request_fields=30,
                           limit_request_field_size=4096, forwarded_allow_ips='',
                           secure_scheme_headers={}, http_protocols='h1', http2_cleartext='off',
                           control_socket_disable=True, http_parser='python')
            if config['lan'] and config['scheme']=='https':
                options.update(certfile=str(common.WEB_DIR / (prefix+'certificate.pem')),
                               keyfile=str(common.WEB_DIR / (prefix+'key.pem')), ssl_context=tls_context)
            for key, value in options.items():
                self.cfg.set(key, value)
        def load(self):
            return create_app(config)
    Server().run()


if __name__ == '__main__':
    main()
