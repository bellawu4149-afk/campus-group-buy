const CREATION_METHODS = [
  {
    id: 'clone',
    title: '复制历史团购开团',
    description: '复用历史团购的商品、价格和排序，快速创建下一团。',
    available: true
  },
  {
    id: 'blank',
    title: '创建空白团购',
    description: '从零开始配置商品和团购内容。',
    available: false
  }
]

Page({
  data: { creationMethods: CREATION_METHODS },
  chooseMethod(e) {
    const methodId = e.currentTarget.dataset.id
    const method = this.data.creationMethods.find(item => item.id === methodId)
    if (!method) return
    if (!method.available) {
      wx.showToast({ title: '即将支持', icon: 'none' })
      return
    }
    if (method.id === 'clone') {
      wx.navigateTo({ url: '/pages/leader-select-clone-source/leader-select-clone-source' })
    }
  }
})
