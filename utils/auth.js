const { API_BASE_URL } = require('./api-config')

const TOKEN_STORAGE_KEY = 'campus_group_buy_access_token'
const USER_STORAGE_KEY = 'campus_group_buy_current_user'
let loginPromise = null

function getToken() {
  return wx.getStorageSync(TOKEN_STORAGE_KEY) || ''
}

function setToken(token) {
  wx.setStorageSync(TOKEN_STORAGE_KEY, token)
}

function clearToken() {
  wx.removeStorageSync(TOKEN_STORAGE_KEY)
  wx.removeStorageSync(USER_STORAGE_KEY)
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const header = { 'content-type': 'application/json' }
    if (token) header.Authorization = `Bearer ${token}`
    wx.request({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      success: res => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        reject({ type: 'response', statusCode: res.statusCode, message: res.data && res.data.detail })
      },
      fail: () => reject({ type: 'network', message: '无法连接登录服务' })
    })
  })
}

function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: result => result.code
        ? resolve(result.code)
        : reject({ type: 'wechat', message: '微信登录未返回有效凭证' }),
      fail: () => reject({ type: 'wechat', message: '微信登录失败' })
    })
  }).then(code => request('/auth/wechat/login', { method: 'POST', data: { code } }))
    .then(result => {
      setToken(result.access_token)
      wx.setStorageSync(USER_STORAGE_KEY, result.user)
      // 不只相信登录响应；保存 Token 后立即通过受保护接口验证一次。
      return me()
    })
}

function getCurrentUser() {
  return wx.getStorageSync(USER_STORAGE_KEY) || null
}

function me() {
  if (!getToken()) return Promise.reject({ type: 'unauthenticated', message: '尚未登录' })
  return request('/auth/me').then(user => {
    wx.setStorageSync(USER_STORAGE_KEY, user)
    return user
  })
}

function ensureLogin() {
  if (!loginPromise) {
    const attempt = getToken()
      ? me().catch(() => {
        clearToken()
        return login()
      })
      : login()

    loginPromise = attempt
      .catch(error => {
        clearToken()
        throw error
      })
      // 避免依赖部分基础库可能缺失的 Promise.prototype.finally。
      .then(
        user => {
          loginPromise = null
          return user
        },
        error => {
          loginPromise = null
          throw error
        }
      )
  }
  return loginPromise
}

function authenticatedRequest(path, options = {}) {
  return ensureLogin()
    .then(() => request(path, options))
    .catch(error => {
      // 只对服务端明确拒绝认证的 401 恢复一次；网络超时等结果未知时绝不重发。
      if (!error || error.statusCode !== 401) throw error
      clearToken()
      return login().then(() => request(path, options))
    })
}

module.exports = {
  TOKEN_STORAGE_KEY,
  USER_STORAGE_KEY,
  login,
  ensureLogin,
  getToken,
  setToken,
  clearToken,
  getCurrentUser,
  me,
  authenticatedRequest
}
