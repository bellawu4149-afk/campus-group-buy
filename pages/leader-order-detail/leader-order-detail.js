const { loadLeaderOrder, getLeaderErrorMessage } = require('../../utils/leader-api')

const ORDER_STATUS = { submitted: '已提交' }

function formatTime(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}` : (value || '未记录')
}

function formatPickup(type, location) {
  if (!type || location === null || location === undefined || location === '') return '未记录'
  return type === 'dormitory' ? `学生公寓 ${location}栋` : String(location)
}

Page({
  data: { orderId: null, loading: true, errorMessage: '', order: null },
  onLoad(options) {
    const orderId = Number(options.order_id)
    if (!Number.isInteger(orderId) || orderId <= 0) {
      this.setData({ loading: false, errorMessage: '订单参数无效' })
      return
    }
    this.setData({ orderId })
    this.loadData()
  },
  loadData() {
    if (!this.data.orderId) return
    this.setData({ loading: true, errorMessage: '' })
    loadLeaderOrder(this.data.orderId).then(order => {
      this.setData({
        loading: false,
        order: Object.assign({}, order, {
          status_display: ORDER_STATUS[order.status] || order.status,
          phone_display: order.customer_phone || '未记录',
          pickup_display: formatPickup(order.pickup_type, order.pickup_location),
          created_at_display: formatTime(order.created_at)
        })
      })
    }).catch(error => {
      this.setData({ loading: false, order: null, errorMessage: getLeaderErrorMessage(error) })
    })
  }
})
