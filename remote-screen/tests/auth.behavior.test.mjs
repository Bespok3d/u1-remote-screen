import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import vm from 'node:vm'

// Behavioral tests for the screen's auth credential logic. The bugs that bit us three times
// (stale-token lockout, the "anonymous" retry that still sent a cookie, the leftover key from the
// printer's other IP that re-seeded the cookie) were all logic, not a missing string - so these load
// the REAL auth.js into a vm with stubbed browser globals and exercise its functions, instead of
// grepping the source.

const AUTH_JS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../files/html/auth.js'), 'utf8')

function makeLocalStorage() {
  // Stored items are OWN enumerable props (so Object.keys(localStorage) returns only keys, like a
  // browser); the accessors live on the prototype so they never show up in removeStoredByPrefix.
  class LocalStorageStub {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(this, key) ? this[key] : null
    }
    setItem(key, value) {
      this[key] = String(value)
    }
    removeItem(key) {
      delete this[key]
    }
  }

  return new LocalStorageStub()
}

function makeDocument() {
  const jar = new Map()
  const doc = {}
  function isExpiry(attr) {
    return /^max-age=0$/i.test(attr) || /^expires=.*197\d/i.test(attr)
  }
  Object.defineProperty(doc, 'cookie', {
    get() {
      return Array.from(jar.entries()).map(function (entry) { return `${entry[0]}=${entry[1]}` }).join('; ')
    },
    set(raw) {
      const parts = raw.split(';').map(function (segment) { return segment.trim() })
      const nameValue = parts[0]
      const eq = nameValue.indexOf('=')
      const name = nameValue.slice(0, eq)
      const value = nameValue.slice(eq + 1)
      const deleting = value === '' || parts.slice(1).some(isExpiry)
      if (deleting) { jar.delete(name); return }
      jar.set(name, value)
    },
  })

  return doc
}

// The printer the stub browser is pointed at, and a second printer address for the cross-host cases.
// auth.js derives every credential key from window.location.host, so the tests derive them the same
// way instead of spelling the slug out: a hardcoded slug silently stopped matching when the fixture
// host moved off the real LAN address, and three tests asserted against keys nothing ever wrote.
const STUB_PRINTER_HOST = '192.0.2.109'
const OTHER_PRINTER_HOST = '192.0.2.66'

function credentialKey(prefix, printerHost) {
  return `${prefix}-${printerHost.replace(/[^a-zA-Z0-9]/g, '_')}`
}

function loadAuth(options) {
  const search = (options && options.search) || ''
  const host = (options && options.host) || STUB_PRINTER_HOST
  const fetchImpl = (options && options.fetch) || function () { throw new Error('fetch not stubbed') }
  const sandbox = {
    localStorage: makeLocalStorage(),
    document: makeDocument(),
    window: { location: { host, search } },
    fetch: fetchImpl,
    URLSearchParams,
    console,
  }
  vm.createContext(sandbox)
  vm.runInContext(AUTH_JS, sandbox)

  return sandbox
}

function cookieNames(doc) {
  return doc.cookie
    .split(';')
    .map(function (segment) { return segment.trim().split('=')[0] })
    .filter(Boolean)
}

test('getAuthHeaders prefers an API key, then a JWT, then nothing', () => {
  const auth = loadAuth()
  // Spread the vm-context object into a host-realm plain object so deepStrictEqual's prototype
  // check compares against the test's own {} literal rather than the vm realm's Object.prototype.
  assert.deepEqual({ ...auth.getAuthHeaders() }, {})

  auth.localStorage.setItem(credentialKey('user-token', STUB_PRINTER_HOST), 'jwt1')
  assert.deepEqual({ ...auth.getAuthHeaders() }, { Authorization: 'Bearer jwt1' })

  auth.localStorage.setItem(credentialKey('screen-apikey', STUB_PRINTER_HOST), 'key1')
  assert.deepEqual({ ...auth.getAuthHeaders() }, { 'X-Api-Key': 'key1' })
})

test('getJWT falls back to a user-token from any host slug (the .109/.66 flip-flop)', () => {
  const auth = loadAuth()
  auth.localStorage.setItem(credentialKey('user-token', OTHER_PRINTER_HOST), 'jwt66')
  assert.equal(auth.getJWT(), 'jwt66')
})

test('captureApiKeyFromUrl stores ?api_key= and ?apikey=', () => {
  const withUnderscore = loadAuth({ search: '?api_key=abc' })
  withUnderscore.captureApiKeyFromUrl()
  assert.equal(withUnderscore.getApiKey(), 'abc')

  const withoutUnderscore = loadAuth({ search: '?apikey=def' })
  withoutUnderscore.captureApiKeyFromUrl()
  assert.equal(withoutUnderscore.getApiKey(), 'def')
})

test('applyStreamCookie carries the right credential as the stream cookie', () => {
  const withJwt = loadAuth()
  withJwt.localStorage.setItem(credentialKey('user-token', STUB_PRINTER_HOST), 'jwtX')
  withJwt.applyStreamCookie()
  assert.equal(cookieNames(withJwt.document).includes('screen_token'), true)
  assert.equal(cookieNames(withJwt.document).includes('screen_apikey'), false)

  const withKey = loadAuth()
  withKey.localStorage.setItem(credentialKey('screen-apikey', STUB_PRINTER_HOST), 'keyX')
  withKey.applyStreamCookie()
  assert.equal(cookieNames(withKey.document).includes('screen_apikey'), true)
  assert.equal(cookieNames(withKey.document).includes('screen_token'), false)

  const open = loadAuth()
  open.applyStreamCookie()
  assert.deepEqual(cookieNames(open.document), [])
})

test('clearStoredCredentials wipes every host slug + the cookies, and nothing re-seeds them', () => {
  const auth = loadAuth()
  auth.localStorage.setItem(credentialKey('user-token', STUB_PRINTER_HOST), 'a')
  auth.localStorage.setItem(credentialKey('user-token', OTHER_PRINTER_HOST), 'b')
  auth.localStorage.setItem(credentialKey('refresh-token', OTHER_PRINTER_HOST), 'r')
  auth.localStorage.setItem(credentialKey('screen-apikey', STUB_PRINTER_HOST), 'k')
  auth.applyStreamCookie()

  auth.clearStoredCredentials()

  assert.equal(auth.getJWT(), null)
  assert.equal(auth.getApiKey(), null)
  assert.deepEqual(Object.keys(auth.localStorage), [])
  assert.deepEqual(cookieNames(auth.document), [])

  // The exact regression: showStream() calls applyStreamCookie() right after the wipe. A leftover
  // token from the other host slug used to be re-read here and re-set the stale stream cookie.
  auth.applyStreamCookie()
  assert.deepEqual(cookieNames(auth.document), [])
})

test('login stores the token + refresh token', async () => {
  const auth = loadAuth({
    fetch: function () {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ result: { token: 't', refresh_token: 'rt' } }) } })
    },
  })
  assert.equal(await auth.login('u', 'p'), true)
  assert.equal(auth.getJWT(), 't')
  assert.equal(auth.localStorage.getItem(credentialKey('refresh-token', STUB_PRINTER_HOST)), 'rt')
})

function response(ok, status) {
  return { ok, status: status || (ok ? 200 : 500) }
}

// Records each probe call's `authed` flag so a test can assert an anonymous retry actually happened.
function probeRecorder(verdicts) {
  const calls = []
  let index = 0
  function probe(authed) {
    calls.push(authed)
    const verdict = verdicts[index] || verdicts[verdicts.length - 1]
    index += 1

    return Promise.resolve(verdict)
  }

  return { probe, calls }
}

test('resolveStreamAccess: authenticated/open probe -> stream', async () => {
  const auth = loadAuth()
  const rec = probeRecorder([response(true)])
  assert.equal(await auth.resolveStreamAccess(rec.probe, true), 'stream')
  assert.deepEqual(rec.calls, [true])
})

test('resolveStreamAccess: a transient non-401 failure -> retry (reconnect, no login)', async () => {
  const auth = loadAuth()
  const rec = probeRecorder([response(false, 502)])
  assert.equal(await auth.resolveStreamAccess(rec.probe, true), 'retry')
})

test('resolveStreamAccess: stale credential over an open printer self-heals (401 then anon ok -> stream + wiped)', async () => {
  const auth = loadAuth()
  auth.localStorage.setItem(credentialKey('user-token', OTHER_PRINTER_HOST), 'stale')
  auth.applyStreamCookie()
  // authed probe 401s (stale token), anonymous probe is served (trusted-IP, login off).
  const rec = probeRecorder([response(false, 401), response(true)])
  // allowRefresh=true but there is no refresh token, so refreshSession() is a no-op (returns false).
  assert.equal(await auth.resolveStreamAccess(rec.probe, true), 'stream')
  assert.deepEqual(rec.calls, [true, false])
  assert.equal(auth.getJWT(), null)
  assert.deepEqual(cookieNames(auth.document), [])
})

test('resolveStreamAccess: genuinely gated (401 then anon 401) -> login', async () => {
  const auth = loadAuth()
  const rec = probeRecorder([response(false, 401), response(false, 401)])
  assert.equal(await auth.resolveStreamAccess(rec.probe, true), 'login')
  assert.deepEqual(rec.calls, [true, false])
})

test('resolveStreamAccess: 401 then a successful refresh re-probes authenticated -> stream', async () => {
  const auth = loadAuth({
    fetch: function () {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ result: { token: 'fresh' } }) } })
    },
  })
  auth.localStorage.setItem(credentialKey('refresh-token', STUB_PRINTER_HOST), 'rt')
  // First authed probe 401s; after refresh, the retry (still authed) is served.
  const rec = probeRecorder([response(false, 401), response(true)])
  assert.equal(await auth.resolveStreamAccess(rec.probe, true), 'stream')
  assert.deepEqual(rec.calls, [true, true])
  assert.equal(auth.getJWT(), 'fresh')
})

test('refreshSession needs a stored refresh token and adopts the new JWT', async () => {
  const noToken = loadAuth({ fetch: function () { throw new Error('should not fetch without a refresh token') } })
  assert.equal(await noToken.refreshSession(), false)

  const withToken = loadAuth({
    fetch: function () {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ result: { token: 't2' } }) } })
    },
  })
  withToken.localStorage.setItem(credentialKey('refresh-token', STUB_PRINTER_HOST), 'rt')
  assert.equal(await withToken.refreshSession(), true)
  assert.equal(withToken.getJWT(), 't2')
})
