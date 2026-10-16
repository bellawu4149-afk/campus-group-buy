const { API_BASE_URL } = require('./api-config')
const productCache = {}

function priceToCents(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d{1,2}))?$/)
  if (!match) throw new Error('Invalid product price')

  const cents = Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0'))
  if (!Number.isSafeInteger(cents)) throw new Error('Product price is too large')
  return cents
}

function loadGroupProducts(groupBuyId) {
  if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) {
    return Promise.reject({ type: 'invalid_group' })
  }
  if (productCache[groupBuyId]) return Promise.resolve(productCache[groupBuyId])

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${API_BASE_URL}/group-buys/${groupBuyId}/products`,
      method: 'GET',
      success: res => {
        if (res.statusCode !== 200) {
          reject({ type: 'request' })
          return
        }
        if (!Array.isArray(res.data)) {
          reject({ type: 'invalid_data' })
          return
        }

        try {
          const products = res.data.map(item => {
            if (!item || !Number.isInteger(item.product_id) || item.product_id <= 0) {
              throw new Error('Invalid product id')
            }
            const priceCent = priceToCents(item.sale_price)
            return {
              id: item.product_id,
              name: item.name,
              description: item.description || '',
              emoji: item.emoji || '',
              price: (priceCent / 100).toFixed(2),
              priceCent,
              lastWeekSales: Number(item.last_week_sales) || 0,
              displayOrder: item.display_order
            }
          })
          productCache[groupBuyId] = products
          resolve(products)
        } catch (error) {
          reject({ type: 'invalid_data' })
        }
      },
      fail: () => reject({ type: 'request' })
    })
  })
}

function getProductsErrorMessage(error) {
  return error && error.type === 'empty'
    ? '暂无可购买商品'
    : '商品加载失败，请稍后重试'
}

module.exports = { loadGroupProducts, getProductsErrorMessage, priceToCents }
