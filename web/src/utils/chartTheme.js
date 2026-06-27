// 浅色护眼主题下的 ECharts 公共配色 / 配置
// 单一来源,供各视图图表复用,避免每处硬编码深色值。
// A 股语义:红涨绿跌。

export const UP = '#dc2626'      // 红 = 涨
export const DOWN = '#16a34a'    // 绿 = 跌
export const ACCENT = '#2563eb'  // 品牌蓝
export const CYAN = '#0891b2'
export const PURPLE = '#7c3aed'
export const AMBER = '#d97706'

// 文本/线条/网格基色(与 global.css 令牌一致)
export const TEXT_1 = '#1e293b'
export const TEXT_2 = '#64748b'
export const TEXT_3 = '#94a3b8'
export const BORDER = '#e2e8f0'
export const BORDER_LIGHT = '#cbd5e1'
export const SPLIT = '#eef2f7'
export const SURFACE = '#ffffff'

// 多系列调色板(折线/柱状对比用,白底可读)
export const PALETTE = [ACCENT, CYAN, PURPLE, AMBER, '#db2777', '#0d9488', '#65a30d', '#9333ea']

// 浅色 tooltip
export const tooltip = (extra = {}) => ({
  backgroundColor: SURFACE,
  borderColor: BORDER,
  borderWidth: 1,
  textStyle: { color: TEXT_1, fontSize: 11 },
  extraCssText: 'box-shadow: 0 8px 24px rgba(15,23,42,0.12); border-radius: 6px;',
  ...extra,
})

// 浅色 category 轴
export const catAxis = (extra = {}) => ({
  type: 'category',
  axisLine: { lineStyle: { color: BORDER_LIGHT } },
  axisTick: { show: false },
  axisLabel: { color: TEXT_2, fontSize: 10 },
  ...extra,
})

// 浅色 value 轴
export const valAxis = (extra = {}) => ({
  type: 'value',
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: TEXT_2, fontSize: 10 },
  splitLine: { lineStyle: { color: SPLIT } },
  ...extra,
})

// 十字准星 axisPointer
export const crossPointer = {
  type: 'cross',
  lineStyle: { color: BORDER_LIGHT },
  crossStyle: { color: BORDER_LIGHT },
  label: { backgroundColor: TEXT_2 },
}
