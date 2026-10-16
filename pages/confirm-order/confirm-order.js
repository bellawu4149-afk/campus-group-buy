const { loadActiveGroupBuyById, getGroupBuyErrorMessage } = require('../../utils/group-buy')
const { loadGroupProducts, getProductsErrorMessage } = require('../../utils/products')
const { readGroupCart, clearGroupCart } = require('../../utils/cart')
const { authenticatedRequest } = require('../../utils/auth')
const ORDER_KEY = 'campus_group_buy_orders'

function formatTime(date) {
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatApiTime(value) {
  // 后端统一返回带 +08:00 的 Asia/Shanghai ISO 时间，直接取其北京时间年月日时分。
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}` : String(value)
}

function formatPickupLocation(type, location) {
  return type === 'dormitory' ? `学生公寓 ${location}栋` : location
}

Page({
  data: { groupBuyId: null, groupBuy: null, groupBuyAvailable: false, items: [], totalCount: 0, totalAmount: '0.00', name: '', phone: '', pickupType: '', dormitoryBuilding: '', otherPickupLocation: '', submitting: false },
  onLoad(options) {
    const groupBuyId = Number(options.group_buy_id)
    if (!Number.isInteger(groupBuyId) || groupBuyId <= 0) {
      wx.showToast({ title: '团购参数无效', icon: 'none' })
      return
    }
    this.setData({ groupBuyId })
    loadActiveGroupBuyById(groupBuyId)
      .then(groupBuy => {
        this.setData({ groupBuy, groupBuyAvailable: true })
        return loadGroupProducts(groupBuy.id)
      })
      .then(products => {
        const cart = readGroupCart(groupBuyId)
        const items = products.filter(item => cart[item.id]).map(item => Object.assign({}, item, { quantity: cart[item.id], subtotal: (item.priceCent * cart[item.id] / 100).toFixed(2) }))
        const totalCount = items.reduce((sum, item) => sum + item.quantity, 0)
        const totalCent = items.reduce((sum, item) => sum + item.quantity * item.priceCent, 0)
        this.setData({ items, totalCount, totalAmount: (totalCent / 100).toFixed(2) })
      })
      .catch(error => {
        const message = this.data.groupBuyAvailable ? getProductsErrorMessage(error) : getGroupBuyErrorMessage(error)
        wx.showToast({ title: message, icon: 'none' })
      })
  },
  handleInput(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }) },
  handleDormitoryInput(e) {
    // 数字键盘仍可能产生非预期字符，前端只保留 ASCII 数字；后端继续负责最终校验。
    const dormitoryBuilding = String(e.detail.value || '').replace(/[^0-9]/g, '').slice(0, 3)
    this.setData({ dormitoryBuilding })
    return dormitoryBuilding
  },
  selectPickupType(e) { this.setData({ pickupType: e.currentTarget.dataset.type }) },
  submitOrder() {
    if (this.data.submitting) return
    const { name, phone, pickupType, dormitoryBuilding, otherPickupLocation, items, totalCount, groupBuy, groupBuyAvailable } = this.data
    if (!groupBuyAvailable || !Number.isInteger(groupBuy.id) || groupBuy.id <= 0) {
      wx.showToast({ title: '暂无可用团购活动', icon: 'none' })
      return
    }
    if (!items.length) { wx.showToast({ title: '购物车为空', icon: 'none' }); return }
    const customerName = name.trim()
    const customerPhone = phone.trim()
    if (customerName.length < 1 || customerName.length > 30) {
      wx.showToast({ title: '姓名或昵称需为 1～30 个字符', icon: 'none' })
      return
    }
    if (customerPhone.length < 3 || customerPhone.length > 30 || !/^[0-9+\- ]+$/.test(customerPhone)) {
      wx.showToast({ title: '联系方式仅支持数字、+、-和空格', icon: 'none' })
      return
    }

    let pickupLocation = ''
    if (pickupType === 'dormitory') {
      const building = dormitoryBuilding.trim()
      if (!/^\d+$/.test(building) || Number(building) < 1 || Number(building) > 999) {
        wx.showToast({ title: '请输入 1～999 的楼栋数字', icon: 'none' })
        return
      }
      pickupLocation = String(Number(building))
    } else if (pickupType === 'other') {
      pickupLocation = otherPickupLocation.trim()
      if (pickupLocation.length < 2 || pickupLocation.length > 100) {
        wx.showToast({ title: '请输入 2～100 字的具体位置', icon: 'none' })
        return
      }
    } else {
      wx.showToast({ title: '请选择取货位置', icon: 'none' })
      return
    }

    this.setData({ submitting: true })

    authenticatedRequest('/orders', {
      method: 'POST',
      data: {
        group_buy_id: groupBuy.id,
        customer_name: customerName,
        customer_phone: customerPhone,
        pickup_type: pickupType,
        pickup_location: pickupLocation,
        items: items.map(item => ({
          product_id: item.id,
          quantity: Number(item.quantity)
        }))
      },
    }).then(result => {
        const backendAmount = Number(result.total_amount)
        const followNo = String(result.follow_no || '')
        const backendPickupType = result.pickup_type
        const backendPickupLocation = String(result.pickup_location || '')
        const backendCustomerName = typeof result.customer_name === 'string' ? result.customer_name : ''
        const backendCustomerPhone = typeof result.customer_phone === 'string' ? result.customer_phone : ''
        const isSuccess = result.status === 'success' &&
          result.order_id !== undefined &&
          result.order_no &&
          /^\d{3,}$/.test(followNo) &&
          (backendPickupType === 'dormitory' || backendPickupType === 'other') &&
          backendPickupLocation &&
          backendCustomerName &&
          backendCustomerPhone &&
          Number.isFinite(backendAmount) &&
          result.created_at

        if (!isSuccess) {
          wx.showToast({ title: '订单提交失败，请稍后重试', icon: 'none' })
          throw { type: 'invalid_response', message: '订单提交失败，请稍后重试' }
        }

        const createdAt = formatApiTime(result.created_at)
        const createdDate = new Date(result.created_at)
        const orders = wx.getStorageSync(ORDER_KEY) || []
        const order = {
          id: String(result.order_id),
          backendOrderId: result.order_id,
          orderNo: result.order_no,
          groupId: groupBuy.id,
          groupName: groupBuy.name,
          joinNumber: followNo,
          pickupType: backendPickupType,
          pickupLocation: backendPickupLocation,
          pickupDisplay: formatPickupLocation(backendPickupType, backendPickupLocation),
          items,
          totalAmount: backendAmount.toFixed(2),
          totalCount,
          contact: { name: backendCustomerName, phone: backendCustomerPhone },
          status: '待取货',
          createdAt,
          submittedAt: Number.isNaN(createdDate.getTime()) ? Date.now() : createdDate.getTime()
        }

        wx.setStorageSync(ORDER_KEY, [order].concat(orders))
        clearGroupCart(groupBuy.id)
        wx.redirectTo({ url: `/pages/order-success/order-success?orderId=${order.id}` })
      })
      .catch(error => {
        let message = error && error.message
        if (error && error.statusCode === 409) message = message || '团购已结束，无法继续下单'
        if (error && (error.type === 'wechat' || error.type === 'unauthenticated')) {
          message = '登录失败，请重试后再提交订单'
        }
        if (error && error.type === 'network') {
          message = '网络异常，订单结果未知，请先到“我的订单”核对，勿重复提交'
        }
        wx.showToast({ title: message || '订单提交失败，请稍后重试', icon: 'none' })
      })
      .then(() => {
        this.setData({ submitting: false })
      }, () => {
        this.setData({ submitting: false })
      })
  }
})
