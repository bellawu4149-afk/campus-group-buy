const { loadActiveGroupBuyById, getGroupBuyErrorMessage } = require('../../utils/group-buy')
const { loadGroupProducts, getProductsErrorMessage } = require('../../utils/products')
const { readGroupCart, writeGroupCart } = require('../../utils/cart')
const { loadGroupManagement } = require('../../utils/group-detail-management')

Page({
  data: { groupBuyId: null, groupBuy: null, groupBuyAvailable: false, products: [], productsLoaded: false, productsMessage: '商品加载中…', totalCount: 0, totalAmount: '0.00', management: null, managementUnavailable: false },
  onLoad(options) {
    const groupBuyId = Number(options.group_buy_id)
    if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) {
      this.setData({ productsMessage: '团购参数无效' })
      wx.showToast({ title: '团购参数无效', icon: 'none' })
      return
    }
    this.setData({ groupBuyId })
    this.loadManagement(groupBuyId)
    loadActiveGroupBuyById(groupBuyId)
      .then(groupBuy => {
        this.setData({ groupBuy, groupBuyAvailable: true })
        return loadGroupProducts(groupBuy.id)
      })
      .then(products => {
        this.setData({ productsLoaded: true, productsMessage: products.length ? '' : '暂无可购买商品' })
        this.restoreCart(products)
      })
      .catch(error => {
        const message = this.data.groupBuyAvailable ? getProductsErrorMessage(error) : getGroupBuyErrorMessage(error)
        this.setData({ productsMessage: message })
        wx.showToast({ title: message, icon: 'none' })
      })
  },
  onShow() {
    if (this.data.productsLoaded) this.restoreCart(this.data.products)
    if (this.data.groupBuyId) this.loadManagement(this.data.groupBuyId)
  },
  loadManagement(groupBuyId) {
    if (this._managementLoadingFor === groupBuyId) return
    this._managementLoadingFor = groupBuyId
    // 每次都先清空，鉴权失败或网络失败时绝不泄露上一次经营数据。
    this.setData({ management: null, managementUnavailable: false })
    loadGroupManagement(groupBuyId).then(result => {
      this._managementLoadingFor = null
      if (result.state === 'owned') {
        this.setData({
          management: {
            orderCount: result.dashboard.summary.order_count,
            totalAmount: result.dashboard.summary.total_amount
          }
        })
        return
      }
      if (result.state === 'unavailable') {
        this.setData({ managementUnavailable: true })
      }
    })
  },
  restoreCart(products) {
    const saved = readGroupCart(this.data.groupBuyId)
    const list = products.map(item => Object.assign({}, item, { quantity: saved[item.id] || 0 }))
    this.updateCart(list)
  },
  increaseQuantity(e) {
    this.changeQuantity(e.currentTarget.dataset.id, 1)
  },
  decreaseQuantity(e) {
    this.changeQuantity(e.currentTarget.dataset.id, -1)
  },
  changeQuantity(id, delta) {
    const list = this.data.products.map(item => {
      if (item.id !== id) return item
      return Object.assign({}, item, {
        quantity: Math.max(0, Number(item.quantity) + delta)
      })
    })
    this.updateCart(list)
  },
  updateCart(list) {
    let totalCount = 0
    let totalCent = 0
    const cart = {}
    list.forEach(item => {
      totalCount += item.quantity
      totalCent += item.quantity * item.priceCent
      if (item.quantity > 0) cart[item.id] = item.quantity
    })
    writeGroupCart(this.data.groupBuyId, cart)
    this.setData({ products: list, totalCount, totalAmount: (totalCent / 100).toFixed(2) })
  },
  goConfirm() {
    if (!this.data.totalCount) return
    if (!this.data.groupBuyAvailable || !this.data.productsLoaded) {
      wx.showToast({ title: '暂无可用团购活动', icon: 'none' })
      return
    }
    wx.navigateTo({ url: `/pages/confirm-order/confirm-order?group_buy_id=${this.data.groupBuyId}` })
  },
  openOrderManagement() {
    if (!this.data.management) return
    wx.navigateTo({ url: `/pages/leader-dashboard/leader-dashboard?group_buy_id=${this.data.groupBuyId}` })
  }
})
