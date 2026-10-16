const auth = require('./auth')
const leaderApi = require('./leader-api')

function loadGroupManagement(groupBuyId, dependencies = {}) {
  const ensureLogin = dependencies.ensureLogin || auth.ensureLogin
  const loadLeaderDashboard = dependencies.loadLeaderDashboard || leaderApi.loadLeaderDashboard

  return ensureLogin()
    .then(user => {
      // 此角色来自服务端 /auth/me；本地字段只用于避免 student 发起无意义的管理请求。
      if (!user || user.role !== 'leader') return { state: 'hidden' }
      return loadLeaderDashboard(groupBuyId)
        .then(dashboard => ({ state: 'owned', dashboard }))
        .catch(error => {
          if (error && (error.statusCode === 403 || error.statusCode === 404)) {
            return { state: 'hidden' }
          }
          return { state: 'unavailable' }
        })
    })
    .catch(() => ({ state: 'hidden' }))
}

module.exports = { loadGroupManagement }
