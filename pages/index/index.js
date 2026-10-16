const { loadActiveGroupBuys, getGroupBuyErrorMessage } = require('../../utils/group-buy')

const DEFAULT_GROUP_COVER = '/assets/images/group-cover.png'

// 展示层适配：未来接口提供封面时直接使用，缺失或加载失败时回退本地插画。
function getGroupCover(groupBuy) {
  const candidates = [groupBuy.cover_url, groupBuy.cover, groupBuy.image_url, groupBuy.image]
  return candidates.find(value => typeof value === 'string' && value.trim()) || DEFAULT_GROUP_COVER
}

Page({
  data: { schoolName: '我的校园', loading: true, errorMessage: '', groupBuys: [] },
  onShow() {
    this.loadData()
  },
  loadData() {
    this.setData({ loading: true, errorMessage: '' })
    loadActiveGroupBuys().then(groupBuys => {
      this.setData({
        loading: false,
        groupBuys: groupBuys.map(item => Object.assign({}, item, {
          coverUrl: getGroupCover(item)
        }))
      })
    }).catch(error => {
      this.setData({ loading: false, groupBuys: [], errorMessage: getGroupBuyErrorMessage(error) })
    })
  },
  handleCoverError(e) {
    const groupBuyId = Number(e.currentTarget.dataset.id)
    const index = this.data.groupBuys.findIndex(item => item.id === groupBuyId)
    if (index < 0 || this.data.groupBuys[index].coverUrl === DEFAULT_GROUP_COVER) return
    this.setData({ [`groupBuys[${index}].coverUrl`]: DEFAULT_GROUP_COVER })
  },
  openGroup(e) {
    const groupBuyId = Number(e.currentTarget.dataset.id)
    if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) return
    wx.navigateTo({ url: `/pages/group-detail/group-detail?group_buy_id=${groupBuyId}` })
  }
})
