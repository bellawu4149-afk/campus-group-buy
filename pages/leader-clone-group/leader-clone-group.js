const {
  loadLeaderGroupBuyConfig,
  cloneLeaderGroupBuy,
  getLeaderErrorMessage
} = require('../../utils/leader-api')

Page({
  data: {
    sourceGroupBuyId: null,
    loading: true,
    errorMessage: '',
    config: null,
    name: '',
    creating: false
  },
  onLoad(options) {
    const sourceGroupBuyId = Number(options.source_group_buy_id)
    if (!Number.isInteger(sourceGroupBuyId) || sourceGroupBuyId <= 0) {
      this.setData({ loading: false, errorMessage: '来源团购参数无效' })
      return
    }
    this.setData({ sourceGroupBuyId })
    this.loadData()
  },
  loadData() {
    if (!this.data.sourceGroupBuyId) return
    this.setData({ loading: true, errorMessage: '' })
    loadLeaderGroupBuyConfig(this.data.sourceGroupBuyId).then(config => {
      this.setData({ loading: false, config })
    }).catch(error => {
      this.setData({ loading: false, config: null, errorMessage: getLeaderErrorMessage(error) })
    })
  },
  handleNameInput(e) {
    this.setData({ name: e.detail.value })
  },
  createGroup() {
    if (this.data.creating || !this.data.config) return
    const name = this.data.name.trim()
    if (!name) {
      wx.showToast({ title: '请输入新团名称', icon: 'none' })
      return
    }
    wx.showModal({
      title: '确认创建新团？',
      content: '将复制当前团购的商品配置，新团不会包含任何历史订单。',
      cancelText: '取消',
      confirmText: '确认创建',
      success: result => {
        if (!result.confirm) return
        this.setData({ creating: true })
        cloneLeaderGroupBuy(this.data.sourceGroupBuyId, name).then(response => {
          const newGroupBuyId = response && response.group_buy && Number(response.group_buy.id)
          if (response.status !== 'success' || !Number.isInteger(newGroupBuyId) || newGroupBuyId <= 0) {
            throw { message: '新团创建结果无效' }
          }
          wx.redirectTo({
            url: `/pages/leader-dashboard/leader-dashboard?group_buy_id=${newGroupBuyId}`
          })
        }).catch(error => {
          this.setData({ creating: false })
          wx.showToast({ title: getLeaderErrorMessage(error), icon: 'none' })
        })
      }
    })
  }
})
