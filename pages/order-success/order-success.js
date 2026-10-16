const ORDER_KEY = 'campus_group_buy_orders'

Page({
  data: { order: null },
  onLoad(options) {
    const orders = wx.getStorageSync(ORDER_KEY) || []
    const order = orders.find(item => item.id === options.orderId)
    if (!order) {
      wx.showToast({ title: '未找到订单', icon: 'none' })
      return
    }
    this.setData({ order })
  },
  viewOrders() { wx.switchTab({ url: '/pages/orders/orders' }) },
  backHome() { wx.switchTab({ url: '/pages/index/index' }) }
})
