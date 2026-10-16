const assert = require('assert')
const { loadGroupManagement } = require('../utils/group-detail-management')

async function run() {
  let dashboardCalls = 0
  const student = await loadGroupManagement(1, {
    ensureLogin: () => Promise.resolve({ id: 2, role: 'student' }),
    loadLeaderDashboard: () => { dashboardCalls += 1; return Promise.resolve({}) }
  })
  assert.deepStrictEqual(student, { state: 'hidden' })
  assert.strictEqual(dashboardCalls, 0)

  const anonymous = await loadGroupManagement(1, {
    ensureLogin: () => Promise.reject({ type: 'wechat' }),
    loadLeaderDashboard: () => Promise.resolve({})
  })
  assert.deepStrictEqual(anonymous, { state: 'hidden' })

  const dashboard = { summary: { order_count: 14, total_amount: '402.80' } }
  const owner = await loadGroupManagement(1, {
    ensureLogin: () => Promise.resolve({ id: 1, role: 'leader' }),
    loadLeaderDashboard: groupBuyId => {
      assert.strictEqual(groupBuyId, 1)
      return Promise.resolve(dashboard)
    }
  })
  assert.deepStrictEqual(owner, { state: 'owned', dashboard })

  for (const statusCode of [403, 404]) {
    const otherLeader = await loadGroupManagement(99, {
      ensureLogin: () => Promise.resolve({ id: 3, role: 'leader' }),
      loadLeaderDashboard: () => Promise.reject({ statusCode })
    })
    assert.deepStrictEqual(otherLeader, { state: 'hidden' })
  }

  const unavailable = await loadGroupManagement(1, {
    ensureLogin: () => Promise.resolve({ id: 1, role: 'leader' }),
    loadLeaderDashboard: () => Promise.reject({ type: 'network' })
  })
  assert.deepStrictEqual(unavailable, { state: 'unavailable' })

  let pageDefinition = null
  let navigatedUrl = null
  global.Page = definition => { pageDefinition = definition }
  global.wx = { navigateTo: options => { navigatedUrl = options.url } }
  require('../pages/group-detail/group-detail.js')
  pageDefinition.openOrderManagement.call({ data: { management: { orderCount: 1 }, groupBuyId: 7 } })
  assert.strictEqual(navigatedUrl, '/pages/leader-dashboard/leader-dashboard?group_buy_id=7')
}

run()
  .then(() => console.log('Integrated group detail management tests passed.'))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
