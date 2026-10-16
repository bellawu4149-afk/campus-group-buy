const CART_KEY = 'campus_group_buy_cart'
const CART_VERSION_KEY = 'campus_group_buy_cart_version'
const CART_VERSION = 3
const auth = require('./utils/auth')

App({
  onLaunch() {
    // V3 开始按 group_buy_id 分键保存购物车；无法判断所属团购的旧全局购物车只清理一次。
    if (wx.getStorageSync(CART_VERSION_KEY) !== CART_VERSION) {
      wx.removeStorageSync(CART_KEY)
      wx.setStorageSync(CART_VERSION_KEY, CART_VERSION)
    }
    // 启动即触发一次认证；失败不阻塞匿名业务，也不自动无限重试。
    auth.ensureLogin().catch(error => {
      // 仅输出安全的错误分类，禁止输出 Token、openid 或微信敏感响应。
      console.warn('微信登录初始化失败', {
        type: error && error.type,
        statusCode: error && error.statusCode,
        message: error && error.message
      })
    })
  },
  globalData: {
    cartStorageKeyPrefix: `${CART_KEY}_`,
    orderStorageKey: 'campus_group_buy_orders',
    feedbackStorageKey: 'campus_group_buy_feedback'
  }
})
