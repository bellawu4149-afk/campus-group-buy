const { API_BASE_URL } = require('./api-config')
const { authenticatedRequest, ensureLogin, getToken, clearToken } = require('./auth')

function request(path, method = 'GET', data) {
  return authenticatedRequest(path, { method, data })
}

function loadLeaderDashboard(groupBuyId) {
  return request(`/leader/group-buys/${groupBuyId}/dashboard`)
}

function loadLeaderOrders(groupBuyId) {
  return request(`/leader/group-buys/${groupBuyId}/orders`)
}

function loadLeaderOrder(orderId) {
  return request(`/leader/orders/${orderId}`)
}

function closeLeaderGroupBuy(groupBuyId) {
  return request(`/leader/group-buys/${groupBuyId}/close`, 'POST')
}

function downloadLeaderExport(groupBuyId) {
  function download() {
    return new Promise((resolve, reject) => {
      wx.downloadFile({
        url: `${API_BASE_URL}/leader/group-buys/${groupBuyId}/export.xlsx`,
        header: { Authorization: `Bearer ${getToken()}` },
        success: result => {
          if (result.statusCode === 200 && result.tempFilePath) {
            resolve(result)
            return
          }
          reject({ type: 'response', statusCode: result.statusCode, message: '备货表下载失败' })
        },
        fail: () => reject({ type: 'network', message: '无法连接后端服务' })
      })
    })
  }
  return ensureLogin().then(download).catch(error => {
    if (!error || error.statusCode !== 401) throw error
    clearToken()
    return ensureLogin().then(download)
  })
}

function loadLeaderGroupBuyConfig(groupBuyId) {
  return request(`/leader/group-buys/${groupBuyId}/config`)
}

function loadLeaderGroupBuys() {
  return request('/leader/group-buys')
}

function cloneLeaderGroupBuy(sourceGroupBuyId, name) {
  return request(`/leader/group-buys/${sourceGroupBuyId}/clone`, 'POST', { name })
}

function getLeaderErrorMessage(error) {
  if (error && error.statusCode === 403) return '当前账号没有团长权限'
  if (error && error.statusCode === 404) return '团购不存在或无权访问'
  if (error && error.statusCode === 401) return '登录状态已失效，请重新登录'
  return error && error.message
    ? error.message
    : '数据加载失败，请稍后重试'
}

module.exports = {
  loadLeaderDashboard,
  loadLeaderOrders,
  loadLeaderOrder,
  closeLeaderGroupBuy,
  downloadLeaderExport,
  loadLeaderGroupBuyConfig,
  loadLeaderGroupBuys,
  cloneLeaderGroupBuy,
  getLeaderErrorMessage
}
