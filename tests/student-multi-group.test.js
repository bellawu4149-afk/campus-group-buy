const assert = require('assert')

const storage = {}
global.wx = {
  getStorageSync(key) { return storage[key] },
  setStorageSync(key, value) { storage[key] = value },
  removeStorageSync(key) { delete storage[key] }
}

const { getCartStorageKey, readGroupCart, writeGroupCart, clearGroupCart } = require('../utils/cart')

assert.strictEqual(getCartStorageKey(1), 'campus_group_buy_cart_1')
assert.strictEqual(getCartStorageKey(2), 'campus_group_buy_cart_2')
assert.throws(() => getCartStorageKey(0))
writeGroupCart(1, { 101: 2 })
writeGroupCart(2, { 202: 3 })
assert.deepStrictEqual(readGroupCart(1), { 101: 2 })
assert.deepStrictEqual(readGroupCart(2), { 202: 3 })
clearGroupCart(1)
assert.deepStrictEqual(readGroupCart(1), {})
assert.deepStrictEqual(readGroupCart(2), { 202: 3 })

console.log('Student multi-group cart isolation tests passed.')
