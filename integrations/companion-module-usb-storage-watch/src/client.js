// SPDX-License-Identifier: MIT
import http from 'node:http'
import https from 'node:https'

const RETRYABLE_STATUS = new Set(['fleet-status','docker-overview','session'])

export class ApiError extends Error {
  constructor(message, kind = 'failed') { super(message); this.kind = kind }
}
export function serverURL(value) {
  let url
  try { url = new URL(value) } catch { throw new ApiError('Enter the complete Storage Watch server URL.', 'config') }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/')
    throw new ApiError('Use an HTTP(S) server origin without credentials, path or query.', 'config')
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
    throw new ApiError('HTTP is allowed only on localhost. Use verified HTTPS for a network address.', 'config')
  return url
}
export class Client {
  constructor(config, token, diagnostic = () => {}) {
    this.diagnostic = diagnostic; this.sequence = 0
    this.url = serverURL(config.url); this.token = token || ''; this.ca = config.ca?.trim() || undefined
    if (!/^usw(?:7_[1-9][0-9]{0,9}_[tr])?_[A-Za-z0-9_-]{43}$/.test(this.token)) throw new ApiError('Enter the dashboard management token (usw7_ or legacy usw_), not a legacy integration token.', 'auth')
    this.cookie = ''; this.csrf = ''; this.session = 0; this.pending = new Set(); this.closed = false
  }
  scrub(value) {
    let result = String(value || 'Request failed.')
    for (const secret of [this.token, this.csrf, this.cookie, ...this.cookie.split(';').map(v => v.trim().split('=').slice(1).join('=')).filter(Boolean)]) if (secret) result = result.split(secret).join('[redacted]')
    return result.replaceAll(/usw(?:7_\d+_[tr])?_[A-Za-z0-9_-]{43}/g, '[redacted]').slice(0, 1200)
  }
  close() { this.closed = true; for (const req of this.pending) req.destroy(); this.cookie = ''; this.csrf = '' }
  async login() {
    if (this.cookie) return
    if (!this.loginTask) this.loginTask = this.raw('login', { management_token: this.token }).then(value => {
      if (!this.cookie || typeof value.csrf !== 'string') throw new ApiError('Login returned an incomplete session.', 'auth')
      this.csrf = value.csrf; this.session++
    }).finally(() => { this.loginTask = null })
    return this.loginTask
  }
  async request(path, data, timeout = 8000) {
    await this.login()
    // Only these side-effect-free reads may retry once, within the original budget.
    // Never replay a POST, login, review/snapshot GET, HTTP refusal or partial reply.
    const started = performance.now()
    try { return await this.raw(path, data, timeout) } catch (error) {
      const r=error.request, remaining=timeout-(performance.now()-started)
      if (data !== undefined || !RETRYABLE_STATUS.has(path) || r?.code !== 'ECONNRESET' ||
          r.reused_socket !== true || r.http_status !== null || this.closed || remaining <= 0 ||
          this.url.protocol === 'https:' && r.tls_verified !== true) throw error
      return this.raw(path, undefined, remaining, {fresh:true,retryOf:r.request_id})
    }
  }
  raw(path, data, timeout = 8000, retry = {}) {
    const read = data === undefined
    if (this.closed) return Promise.reject(new ApiError(read ? 'Connection replaced; status unavailable.' : 'Connection replaced; outcome may be uncertain.', 'offline'))
    const body = data === undefined ? undefined : JSON.stringify(data)
    const endpoint = new URL('/api/' + path, this.url).pathname, method = body === undefined ? 'GET' : 'POST'
    const operation = ['sleep','mount','unmount','start','stop','restart'].includes(data?.action) ? data.action : endpoint.split('/').at(-1)
    const started = performance.now(), requestId = ++this.sequence
    return new Promise((resolve, reject) => {
      let req, timer, settled = false, status = null
      const finish = (error, value, code = null) => {
        if (settled) return
        settled = true; clearTimeout(timer); this.pending.delete(req)
        const detail = {request_id:requestId, attempt:retry.fresh?2:1, ...(retry.fresh?{retry_of:retry.retryOf,fresh_connection:true}:{}), operation, method, endpoint, elapsed_ms:Math.round(performance.now()-started), http_status:status, code, reused_socket:req?.reusedSocket === true, ...(this.url.protocol === 'https:' ? {tls_verified:req?.socket?.authorized === true} : {}),
          result:error ? error.kind : 'response', ...(error ? {error:this.scrub(error.message)} : {})}
        try { this.diagnostic(detail) } catch {} // Logging must never change an operation's outcome.
        if (error) {
          error.request = detail
          error.message = `${method} ${endpoint}: ${this.scrub(error.message)} (${code || 'HTTP '+(status ?? 'unknown')}; ${detail.elapsed_ms} ms)`
          reject(error)
        } else resolve(value)
      }
      req = (this.url.protocol === 'https:' ? https : http).request(new URL('/api/' + path, this.url), {
        method, ...(retry.fresh ? {agent:false} : {}), rejectUnauthorized: true, ca: this.ca, minVersion: 'TLSv1.2',
        headers: {Origin:this.url.origin, 'X-USW-Request':'1', 'Content-Type':'application/json', Cookie:this.cookie, 'X-CSRF-Token':this.csrf},
      }, response => {
        status = response.statusCode
        let bytes = 0; const chunks = []
        response.on('data', chunk => {
          bytes += chunk.length
          if (bytes > 2 * 1024 * 1024) {
            finish(new ApiError(read ? 'Status response exceeded its size limit.' : 'Response exceeded its size limit. Outcome is unverified.', 'offline'), null, 'RESPONSE_TOO_LARGE'); req.destroy()
          } else chunks.push(chunk)
        })
        response.on('error', error => finish(new ApiError(read ? 'Status response interrupted.' : 'Response interrupted. Inspect status; do not replay a command.', 'offline'), null, error.code || 'RESPONSE_INTERRUPTED'))
        response.on('end', () => {
          if (settled) return
          if (status >= 300 && status < 400) return finish(new ApiError('Server redirected the request. Check its URL; credentials were not forwarded.', 'config'), null, 'REDIRECT')
          let value
          try { value = JSON.parse(Buffer.concat(chunks).toString()) } catch { return finish(new ApiError(read ? 'Status response was not valid JSON.' : 'Server response was not valid JSON. Outcome is unverified.', 'offline'), null, 'INVALID_JSON') }
          if (!value || typeof value !== 'object' || Array.isArray(value)) return finish(new ApiError(read ? 'Status response was not a JSON object.' : 'Server response was not a JSON object. Outcome is unverified.', 'offline'), null, 'INVALID_RESPONSE')
          if (status === 401) {
            const message = this.scrub(value.error || 'Authentication failed. Check the management token.'); this.cookie = ''; this.csrf = ''
            return finish(new ApiError(message, 'auth'), null, 'AUTHENTICATION')
          }
          if (status !== 200) return finish(new ApiError(this.scrub(value.error || 'Storage Watch refused the request.'), status >= 500 ? 'unavailable' : 'refused'), null, 'HTTP_ERROR')
          if (path === 'login') this.cookie = (response.headers['set-cookie'] || []).map(v => v.split(';')[0]).join('; ')
          finish(null, value)
        })
      })
      this.pending.add(req)
      timer = setTimeout(() => req.destroy(Object.assign(new Error('Request deadline expired'), {code:'USW_TIMEOUT'})), timeout)
      req.on('error', error => {
        const code = /^[A-Z0-9_]{1,64}$/.test(error.code || '') ? error.code : 'SOCKET_ERROR'
        const tls = ['CERT_HAS_EXPIRED','DEPTH_ZERO_SELF_SIGNED_CERT','UNABLE_TO_VERIFY_LEAF_SIGNATURE','ERR_TLS_CERT_ALTNAME_INVALID','SELF_SIGNED_CERT_IN_CHAIN'].includes(code)
        finish(new ApiError(tls ? 'HTTPS verification failed. Check the server address and trusted public CA; verification remains enabled.'
          : code === 'USW_TIMEOUT' ? read ? 'Status request timed out.' : 'Request timed out. Its outcome is unverified; no command was resent.'
          : read ? 'Status connection failed.' : 'Connection failed. Its outcome is unverified; no command was resent.', 'offline'), null, code)
      })
      req.end(body)
    })
  }
}
