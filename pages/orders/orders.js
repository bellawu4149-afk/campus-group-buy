const { authenticatedRequest } = require('../../utils/auth')

function formatApiTime(value) {
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}` : String(value)
}

function formatPickupLocation(type, location) {
  if (!type || !location) return '未记录'
  return type === 'dormitory' ? `学生公寓 ${location}栋` : location
}

function normalizeOrder(order) {
  const items = (order.items || []).map((item, index) => ({
    id: `${order.id}-${index}`,
    name: item.product_name,
    unitPrice: Number(item.unit_price).toFixed(2),
    quantity: item.quantity,
    subtotal: Number(item.subtotal).toFixed(2)
  }))
  return {
    id: order.id,
    orderNo: order.order_no,
    groupId: order.group_buy_id,
    groupName: order.group_buy_name,
    joinNumber: order.follow_no,
    status: order.status === 'submitted' ? '待取货' : order.status,
    totalAmount: Number(order.total_amount).toFixed(2),
    totalCount: items.reduce((sum, item) => sum + item.quantity, 0),
    createdAt: formatApiTime(order.created_at),
    contact: { name: order.customer_name, phone: order.customer_phone || '未记录' },
    pickupDisplay: formatPickupLocation(order.pickup_type, order.pickup_location),
    items
  }
}

Page({
  data: { orders: [], loading: false, loadFailed: false },
  onShow() {
    this.loadOrders()
  },
  loadOrders() {
    if (this.data.loading) return
    this.setData({ loading: true, loadFailed: false })
    authenticatedRequest('/orders/mine')
      .then(orders => {
        if (!Array.isArray(orders)) throw { type: 'invalid_response' }
        this.setData({ orders: orders.map(normalizeOrder) })
      })
      .catch(() => {
        this.setData({ orders: [], loadFailed: true })
        wx.showToast({ title: '订单加载失败，请稍后重试', icon: 'none' })
      })
      .then(() => this.setData({ loading: false }), () => this.setData({ loading: false }))
  },
  retryLoad() { this.loadOrders() },
  goShopping() { wx.switchTab({ url: '/pages/index/index' }) }
})
