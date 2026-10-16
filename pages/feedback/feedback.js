const { API_BASE_URL } = require('../../utils/api-config')
const FEEDBACK_API_URL = `${API_BASE_URL}/feedback`

Page({
  data: {
    serviceSatisfaction: 0,
    overallExperience: '',
    convenience: '',
    rankingHelpful: '',
    continueUse: '',
    desiredFeatures: [],
    suggestion: '',
    submitting: false,
    submitted: false,
    ratings: [1, 2, 3, 4, 5]
  },

  chooseRating(e) { this.setData({ serviceSatisfaction: Number(e.currentTarget.dataset.value), submitted: false }) },
  chooseExperience(e) { this.setData({ overallExperience: e.detail.value, submitted: false }) },
  chooseConvenience(e) { this.setData({ convenience: e.detail.value, submitted: false }) },
  chooseHelpful(e) { this.setData({ rankingHelpful: e.detail.value, submitted: false }) },
  chooseContinueUse(e) { this.setData({ continueUse: e.detail.value, submitted: false }) },
  chooseDesiredFeatures(e) { this.setData({ desiredFeatures: e.detail.value, submitted: false }) },
  inputSuggestion(e) { this.setData({ suggestion: e.detail.value, submitted: false }) },

  submitFeedback() {
    if (this.data.submitting) return

    const { serviceSatisfaction, overallExperience, convenience, rankingHelpful, continueUse, desiredFeatures, suggestion } = this.data
    const requiredItems = [
      [serviceSatisfaction, '请完成整体满意度评分'],
      [overallExperience, '请选择本次使用体验'],
      [convenience, '请选择使用便利程度'],
      [rankingHelpful, '请选择销量榜是否有帮助'],
      [continueUse, '请选择是否愿意继续使用']
    ]
    const missingItem = requiredItems.find(item => !item[0])
    if (missingItem) {
      wx.showToast({ title: missingItem[1], icon: 'none' })
      return
    }

    this.setData({ submitting: true })
    wx.request({
      url: FEEDBACK_API_URL,
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: {
        overall_experience: overallExperience,
        convenience,
        ranking_helpful: rankingHelpful,
        continue_use: continueUse,
        desired_features: desiredFeatures,
        service_satisfaction: Number(serviceSatisfaction),
        suggestion: suggestion.trim() || null
      },
      success: res => {
        if (res.statusCode === 201 && res.data && res.data.status === 'success') {
          this.setData({ submitted: true })
          wx.showModal({ title: '提交成功', content: '反馈提交成功，感谢你的建议', showCancel: false })
          return
        }
        wx.showToast({ title: '提交失败，请稍后重试', icon: 'none' })
      },
      fail: () => {
        wx.showToast({ title: '无法连接服务，请确认后端已启动', icon: 'none' })
      },
      complete: () => {
        this.setData({ submitting: false })
      }
    })
  }
})
