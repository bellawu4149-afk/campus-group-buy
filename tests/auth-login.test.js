const assert = require('assert')
const path = require('path')

const authPath = path.resolve(__dirname, '../utils/auth.js')
const configPath = path.resolve(__dirname, '../utils/api-config.js')

function loadAuth({ token = '', meStatus = 200 } = {}) {
  delete require.cache[authPath]
  delete require.cache[configPath]
  const storage = {}
  if (token) storage.campus_group_buy_access_token = token
  const requests = []
  let loginCalls = 0

  global.wx = {
    getStorageSync(key) { return storage[key] || '' },
    setStorageSync(key, value) { storage[key] = value },
    removeStorageSync(key) { delete storage[key] },
    login(options) {
      loginCalls += 1
      options.success({ code: 'fresh-wx-code' })
    },
    request(options) {
      requests.push({ url: options.url, method: options.method, header: options.header, data: options.data })
      if (options.url.endsWith('/auth/wechat/login')) {
        options.success({
          statusCode: 200,
          data: {
            access_token: 'new-server-token',
            user: { id: 1, nickname: null, role: 'student', created_at: '2026-10-07T00:00:00+08:00' }
          }
        })
        return
      }
      const statusCode = requests.filter(item => item.url.endsWith('/auth/me')).length === 1
        ? meStatus
        : 200
      options.success({
        statusCode,
        data: statusCode === 200
          ? { id: 1, nickname: null, role: 'student', created_at: '2026-10-07T00:00:00+08:00' }
          : { detail: '认证凭证无效或已过期' }
      })
    }
  }

  return {
    auth: require(authPath),
    storage,
    requests,
    getLoginCalls: () => loginCalls
  }
}

async function testNoTokenLogsInAndVerifiesMe() {
  const fixture = loadAuth()
  await fixture.auth.ensureLogin()
  assert.strictEqual(fixture.getLoginCalls(), 1)
  assert.deepStrictEqual(
    fixture.requests.map(item => `${item.method} ${item.url}`),
    [
      'POST http://127.0.0.1:8000/auth/wechat/login',
      'GET http://127.0.0.1:8000/auth/me'
    ]
  )
  assert.strictEqual(fixture.storage.campus_group_buy_access_token, 'new-server-token')
  assert.strictEqual(fixture.requests[1].header.Authorization, 'Bearer new-server-token')
}

async function testValidStoredTokenOnlyChecksMe() {
  const fixture = loadAuth({ token: 'valid-old-token', meStatus: 200 })
  await fixture.auth.ensureLogin()
  assert.strictEqual(fixture.getLoginCalls(), 0)
  assert.deepStrictEqual(
    fixture.requests.map(item => `${item.method} ${item.url}`),
    ['GET http://127.0.0.1:8000/auth/me']
  )
}

async function testInvalidStoredTokenIsClearedThenReloggedOnce() {
  const fixture = loadAuth({ token: 'invalid-old-token', meStatus: 401 })
  await fixture.auth.ensureLogin()
  assert.strictEqual(fixture.getLoginCalls(), 1)
  assert.deepStrictEqual(
    fixture.requests.map(item => `${item.method} ${item.url}`),
    [
      'GET http://127.0.0.1:8000/auth/me',
      'POST http://127.0.0.1:8000/auth/wechat/login',
      'GET http://127.0.0.1:8000/auth/me'
    ]
  )
  assert.strictEqual(fixture.requests[1].header.Authorization, undefined)
  assert.strictEqual(fixture.storage.campus_group_buy_access_token, 'new-server-token')
}

Promise.resolve()
  .then(testNoTokenLogsInAndVerifiesMe)
  .then(testValidStoredTokenOnlyChecksMe)
  .then(testInvalidStoredTokenIsClearedThenReloggedOnce)
  .then(() => console.log('Frontend auth startup tests passed.'))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
