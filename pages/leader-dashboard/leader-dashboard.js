const {
  loadLeaderDashboard,
  loadLeaderOrders,
  closeLeaderGroupBuy,
  downloadLeaderExport,
  getLeaderErrorMessage
} = require('../../utils/leader-api')

const GROUP_STATUS = { active: '进行中', closed: '已截团' }
const ORDER_STATUS = { submitted: '已提交' }

function formatTime(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}` : (value || '未记录')
}

function formatPickup(type, location) {
  if (!type || location === null || location === undefined || location === '') return '历史未记录'
  return type === 'dormitory' ? `学生公寓 ${location}栋` : String(location)
}

Page({
  data: {
    groupBuyId: 1,
    loading: true,
    errorMessage: '',
    dashboard: null,
    orders: [],
    closing: false,
    exporting: false
  },
  onLoad(options) {
    const parsedId = Number(options.group_buy_id)
    this.setData({ groupBuyId: Number.isInteger(parsedId) && parsedId > 0 ? parsedId : 1 })
    this.loadData()
  },
  loadData() {
    const groupBuyId = this.data.groupBuyId
    this.setData({ loading: true, errorMessage: '' })
    Promise.all([
      loadLeaderDashboard(groupBuyId),
      loadLeaderOrders(groupBuyId)
    ]).then(([dashboard, orders]) => {
      const normalizedDashboard = Object.assign({}, dashboard, {
        group_buy: Object.assign({}, dashboard.group_buy, {
          status_display: GROUP_STATUS[dashboard.group_buy.status] || dashboard.group_buy.status
        })
      })
      const normalizedOrders = (Array.isArray(orders) ? orders : []).map(order => Object.assign({}, order, {
        status_display: ORDER_STATUS[order.status] || order.status,
        pickup_display: formatPickup(order.pickup_type, order.pickup_location),
        phone_display: order.customer_phone || '未记录',
        created_at_display: formatTime(order.created_at)
      }))
      this.setData({ dashboard: normalizedDashboard, orders: normalizedOrders, loading: false })
    }).catch(error => {
      this.setData({
        dashboard: null,
        orders: [],
        loading: false,
        errorMessage: getLeaderErrorMessage(error)
      })
    })
  },
  openOrder(e) {
    const orderId = Number(e.currentTarget.dataset.id)
    if (!Number.isInteger(orderId) || orderId <= 0) return
    wx.navigateTo({ url: `/pages/leader-order-detail/leader-order-detail?order_id=${orderId}` })
  },
  closeGroupBuy() {
    if (this.data.closing || !this.data.dashboard || this.data.dashboard.group_buy.status !== 'active') return
    wx.showModal({
      title: '确认截团？',
      content: '截团后学生将无法继续提交新订单，本团现有订单仍会保留并可继续查看和导出。',
      cancelText: '取消',
      confirmText: '确认截团',
      confirmColor: '#b65c3b',
      success: result => {
        if (!result.confirm) return
        this.setData({ closing: true })
        closeLeaderGroupBuy(this.data.groupBuyId).then(() => {
          this.setData({ closing: false })
          wx.showToast({ title: '截团成功', icon: 'success' })
          this.loadData()
        }).catch(error => {
          this.setData({ closing: false })
          wx.showToast({ title: getLeaderErrorMessage(error), icon: 'none' })
        })
      }
    })
  },
  exportExcel() {
    if (this.data.exporting || !this.data.dashboard || this.data.dashboard.group_buy.status !== 'closed') return
    this.setData({ exporting: true })
    downloadLeaderExport(this.data.groupBuyId)
      .then(result => {
        wx.openDocument({
          filePath: result.tempFilePath,
          fileType: 'xlsx',
          showMenu: true,
          fail: () => wx.showToast({ title: '备货表打开失败', icon: 'none' }),
          complete: () => this.setData({ exporting: false })
        })
      })
      .catch(error => {
        this.setData({ exporting: false })
        wx.showToast({ title: getLeaderErrorMessage(error), icon: 'none' })
      })
  }
})
