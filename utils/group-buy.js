const { API_BASE_URL } = require('./api-config')
const GROUP_BUYS_API_URL = `${API_BASE_URL}/group-buys`

function normalizeGroupBuy(item) {
  if (!item || !Number.isInteger(item.id) || item.id <= 0 ||
      typeof item.name !== 'string' || !item.name.trim() ||
      item.status !== 'active') {
    throw new Error('Invalid active group buy')
  }
  // 仅透传可选封面字符串，保持现有团购校验和业务字段不变。
  const normalized = { id: item.id, name: item.name, status: item.status, created_at: item.created_at || null }
  ;['cover_url', 'cover', 'image_url', 'image'].forEach(key => {
    if (typeof item[key] === 'string' && item[key].trim()) normalized[key] = item[key].trim()
  })
  return normalized
}

function loadActiveGroupBuys() {
  return new Promise((resolve, reject) => {
    wx.request({
      url: GROUP_BUYS_API_URL,
      method: 'GET',
      success: res => {
        if (res.statusCode !== 200 || !Array.isArray(res.data)) {
          reject({ type: 'request' })
          return
        }
        try {
          resolve(res.data.map(normalizeGroupBuy))
        } catch (error) {
          reject({ type: 'invalid_data' })
        }
      },
      fail: () => reject({ type: 'request' })
    })
  })
}

function loadActiveGroupBuyById(groupBuyId) {
  if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) {
    return Promise.reject({ type: 'invalid_group' })
  }
  return loadActiveGroupBuys().then(groupBuys => {
    const groupBuy = groupBuys.find(item => item.id === groupBuyId)
    if (!groupBuy) throw { type: 'not_available' }
    return groupBuy
  })
}

function getGroupBuyErrorMessage(error) {
  return error && (error.type === 'invalid_group' || error.type === 'not_available')
    ? '团购不存在或已截团'
    : '团购活动加载失败，请稍后重试'
}

module.exports = { loadActiveGroupBuys, loadActiveGroupBuyById, getGroupBuyErrorMessage }

