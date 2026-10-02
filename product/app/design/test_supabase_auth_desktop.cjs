const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('desktop serializes PKCE starts so a second login cannot replace the verifier', async () => {
  let resolveOAuth;
  let signInCalls = 0;
  let nonceCount = 0;
  const client = {
    auth: {
      onAuthStateChange() {},
      signInWithOAuth() {
        signInCalls += 1;
        return new Promise(resolve => { resolveOAuth = resolve; });
      },
      async exchangeCodeForSession(code) {
        assert.equal(code, 'synthetic-code');
        return { data: { session: { access_token: 'synthetic-token' } } };
      },
    },
  };
  const storage = {getItem() { return null; }, setItem() {}, removeItem() {}};
  const window = {
    ALEPH_SUPABASE: { url: 'https://synthetic.invalid', anonKey: 'synthetic-anon' },
    supabase: { createClient: () => client },
    __TAURI__: { opener: { openUrl: async () => {} } },
    __ALEPH_LAUNCH_CAP__: 'synthetic-cap',
    crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++nonceCount).padStart(12, '0')}` },
    location: { origin: 'http://127.0.0.1:8080', hash: '', search: '',
      assign() {} },
    fetch: async (url, options) => {
      if (url === '/auth/desktop/start') return { ok: true };
      if (url.startsWith('/auth/desktop/session?')) return {
        status: 200, json: async () => ({ code: 'synthetic-code' }),
      };
      if (url === '/auth/desktop/log') return { ok: true };
      throw new Error(`unexpected fetch: ${url} ${options?.method || ''}`);
    },
    dispatchEvent() {},
  };
  const sandbox = {window, crypto: window.crypto, sessionStorage: storage,
    localStorage: storage, navigator: { onLine: true }, URLSearchParams,
    CustomEvent: class {}, console: {log() {}, warn() {}}, setTimeout};
  const source = fs.readFileSync(path.join(__dirname, 'supabase-auth.js'), 'utf8');
  vm.runInNewContext(source, sandbox);
  const first = window.alephAuth.entrarCon('github');
  for (let n = 0; n < 20 && signInCalls === 0; n++) await Promise.resolve();
  assert.equal(signInCalls, 1);
  await assert.rejects(window.alephAuth.entrarCon('google'), /Ya hay un ingreso en curso/);
  assert.equal(signInCalls, 1);
  resolveOAuth({ data: { url: 'https://synthetic.invalid/authorize' } });
  await first;
  assert.equal(nonceCount, 2); // nonce + independent application state
});

test('a provider denial is returned immediately, not retried until the five-minute deadline', async () => {
  let polls = 0;
  const client = { auth: {
    onAuthStateChange() {},
    async signInWithOAuth() { return {data: {url: 'https://synthetic.invalid/authorize'}}; },
  } };
  const window = {
    ALEPH_SUPABASE: {url: 'https://synthetic.invalid', anonKey: 'synthetic-anon'},
    supabase: {createClient: () => client},
    __TAURI__: {opener: {openUrl: async () => {}}},
    __ALEPH_LAUNCH_CAP__: 'synthetic-cap',
    crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000001'},
    location: {origin: 'http://127.0.0.1:8080', hash: '', search: '', assign() {}},
    fetch: async url => {
      if (url === '/auth/desktop/start') return {ok: true};
      if (url.startsWith('/auth/desktop/session?')) {
        polls += 1;
        return {status: 200, json: async () => ({error: 'access_denied'})};
      }
      if (url === '/auth/desktop/log') return {ok: true};
      throw new Error(`unexpected fetch: ${url}`);
    },
    dispatchEvent() {},
  };
  const storage = {getItem() { return null; }, setItem() {}, removeItem() {}};
  const sandbox = {window, crypto: window.crypto, sessionStorage: storage,
    localStorage: storage, navigator: {onLine: true}, URLSearchParams,
    CustomEvent: class {}, console: {log() {}, warn() {}}, setTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'supabase-auth.js'), 'utf8'), sandbox);
  await assert.rejects(window.alephAuth.entrarCon('github'), /access_denied/);
  assert.equal(polls, 1);
});

test('page reload resumes the pending nonce without overwriting the stored PKCE verifier', async () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  let starts = 0;
  let exchanges = 0;
  let nonces = 0;
  const client = {auth: {
    onAuthStateChange() {},
    async signInWithOAuth() {
      starts += 1;
      return {data: {url: 'https://synthetic.invalid/authorize'}};
    },
    async exchangeCodeForSession(code) {
      assert.equal(code, 'synthetic-code');
      exchanges += 1;
      return {data: {session: {access_token: 'synthetic-token'}}};
    },
  }};
  function page() {
    const window = {
      ALEPH_SUPABASE: {url: 'https://synthetic.invalid', anonKey: 'synthetic-anon'},
      supabase: {createClient: () => client},
      __TAURI__: {opener: {openUrl: () => new Promise(() => {})}},
      __ALEPH_LAUNCH_CAP__: 'synthetic-cap',
      crypto: {randomUUID: () => `00000000-0000-4000-8000-${String(++nonces).padStart(12, '0')}`},
      location: {origin: 'http://127.0.0.1:8080', hash: '', search: '', assign() {}},
      fetch: async url => {
        if (url === '/auth/desktop/start') return {ok: true};
        if (url.startsWith('/auth/desktop/session?')) return {
          status: 200, json: async () => ({code: 'synthetic-code'}),
        };
        if (url === '/auth/desktop/log') return {ok: true};
        throw new Error(`unexpected fetch: ${url}`);
      },
      dispatchEvent() {},
    };
    const sandbox = {window, crypto: window.crypto, sessionStorage: storage,
      localStorage: storage, navigator: {onLine: true}, URLSearchParams,
      CustomEvent: class {}, console: {log() {}, warn() {}}, setTimeout};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'supabase-auth.js'), 'utf8'), sandbox);
    return window;
  }
  const first = page();
  first.alephAuth.entrarCon('github');
  for (let n = 0; n < 20 && !values.has('aleph_desktop_oauth_pending'); n++)
    await Promise.resolve();
  assert.equal(starts, 1);
  assert.ok(values.has('aleph_desktop_oauth_pending'));
  const resumed = page();
  await resumed.alephAuth.entrarCon('github');
  assert.equal(starts, 1);
  assert.equal(exchanges, 1);
  assert.equal(nonces, 2); // resumed page generates neither a new nonce nor state
  assert.equal(values.has('aleph_desktop_oauth_pending'), false);
});

test('ordinary web login still redirects through the provider without desktop mailbox calls', async () => {
  let config;
  let oauth;
  const window = {
    ALEPH_SUPABASE: {url: 'https://synthetic.invalid', anonKey: 'synthetic-anon',
      redirectTo: 'https://web.synthetic.invalid/return'},
    supabase: {createClient: (_url, _key, options) => {
      config = options;
      return {auth: {
        onAuthStateChange() {},
        async signInWithOAuth(request) { oauth = request; return {data: {url: 'https://provider.invalid'}}; },
      }};
    }},
    location: {origin: 'https://web.synthetic.invalid', hash: '', search: ''},
    dispatchEvent() {},
  };
  const storage = {getItem() {return null;}, setItem() {}, removeItem() {}};
  const sandbox = {window, sessionStorage: storage, localStorage: storage,
    navigator: {onLine: true}, URLSearchParams, CustomEvent: class {},
    console: {log() {}, warn() {}}, setTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'supabase-auth.js'), 'utf8'), sandbox);
  await window.alephAuth.entrarCon('github');
  assert.equal(config.auth.flowType, 'pkce');
  assert.equal(oauth.options.redirectTo, 'https://web.synthetic.invalid/return');
  assert.equal(oauth.options.skipBrowserRedirect, undefined);
});
