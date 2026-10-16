const CART_KEY_PREFIX = 'campus_group_buy_cart_'

function getCartStorageKey(groupBuyId) {
  if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) {
    throw new Error('Invalid group_buy_id')
  }
  return `${CART_KEY_PREFIX}${groupBuyId}`
}

function readGroupCart(groupBuyId) {
  const cart = wx.getStorageSync(getCartStorageKey(groupBuyId))
  return cart && typeof cart === 'object' && !Array.isArray(cart) ? cart : {}
}

function writeGroupCart(groupBuyId, cart) {
  wx.setStorageSync(getCartStorageKey(groupBuyId), cart)
}

function clearGroupCart(groupBuyId) {
  wx.removeStorageSync(getCartStorageKey(groupBuyId))
}

module.exports = { getCartStorageKey, readGroupCart, writeGroupCart, clearGroupCart }
