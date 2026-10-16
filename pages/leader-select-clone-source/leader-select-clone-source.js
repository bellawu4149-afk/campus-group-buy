const { loadLeaderGroupBuys, getLeaderErrorMessage } = require('../../utils/leader-api')

const GROUP_STATUS = { active: '进行中', closed: '已截团' }

function formatTime(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}` : (value || '未记录')
}

Page({
  data: { loading: true, errorMessage: '', groupBuys: [] },
  onLoad() {
    this.loadData()
  },
  loadData() {
    this.setData({ loading: true, errorMessage: '' })
    loadLeaderGroupBuys().then(groupBuys => {
      const normalized = (Array.isArray(groupBuys) ? groupBuys : []).map(groupBuy => Object.assign({}, groupBuy, {
        status_display: GROUP_STATUS[groupBuy.status] || groupBuy.status,
        created_at_display: formatTime(groupBuy.created_at)
      }))
      this.setData({ loading: false, groupBuys: normalized })
    }).catch(error => {
      this.setData({ loading: false, groupBuys: [], errorMessage: getLeaderErrorMessage(error) })
    })
  },
  selectSource(e) {
    const sourceGroupBuyId = Number(e.currentTarget.dataset.id)
    if (!Number.isInteger(sourceGroupBuyId) || sourceGroupBuyId <= 0) return
    wx.navigateTo({
      url: `/pages/leader-clone-group/leader-clone-group?source_group_buy_id=${sourceGroupBuyId}`
    })
  }
})
