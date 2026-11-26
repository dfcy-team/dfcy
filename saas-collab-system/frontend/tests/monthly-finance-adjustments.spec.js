// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Panel from '../src/components/finance/MonthlyCostAdjustments.vue'

const api = vi.hoisted(() => vi.fn())
vi.mock('../src/api/request', () => ({ requestApi: api }))

describe('monthly finance adjustments panel', () => {
  beforeEach(() => api.mockReset())
  it('shows errors for unsuccessful API envelopes', async () => {
    api.mockResolvedValue({ success: false, message: '无权读取仓库' })
    const wrapper = mount(Panel); await flushPromises()
    expect(wrapper.text()).toContain('历史调整读取失败：无权读取仓库')
    wrapper.unmount()
  })
  it('requests a local YYYY-MM month and supports selecting another month', async () => {
    api.mockResolvedValue({ data: { success: true, data: { enabled: true, rows: [] } } })
    const wrapper = mount(Panel); await flushPromises()
    const first = api.mock.calls[0][0].params.month
    expect(first).toMatch(/^\d{4}-\d{2}$/)
    await wrapper.find('input[type="month"]').setValue('2026-03'); await flushPromises()
    expect(api.mock.calls[1][0].params.month).toBe('2026-03')
    wrapper.unmount()
  })
  it('renders zero amounts as values and negative profit impact', async () => {
    api.mockResolvedValue({ data: { success: true, data: { enabled: true, rows: [{ warehouse_id: 8, country: 'MY', warehouse: 'WH', inventory_amount: '0.0000', sold_amount: '2.0000', gross_profit_impact: '-2.0000' }] } } })
    const wrapper = mount(Panel); await flushPromises()
    expect(wrapper.text()).toContain('0.0000'); expect(wrapper.text()).toContain('-2.0000')
    wrapper.unmount()
  })
})
