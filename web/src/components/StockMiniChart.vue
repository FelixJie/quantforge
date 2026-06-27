<template>
  <div class="mini-chart" ref="chartContainer">
    <canvas ref="canvas" :style="{ width: width + 'px', height: height + 'px' }"></canvas>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  },
  width: {
    type: Number,
    default: 120
  },
  height: {
    type: Number,
    default: 48
  },
  color: {
    type: String,
    default: null // 'red' or 'green', if null auto detect
  },
  // 分时模式：X 轴按完整交易日(240 分钟)定位，避免盘初寥寥几点被拉满整宽
  intraday: {
    type: Boolean,
    default: true
  },
  // 昨收基准价(用于基准线与涨跌着色)；缺省时用首点兜底
  preClose: {
    type: Number,
    default: null
  }
})

const canvas = ref(null)
const chartContainer = ref(null)

// 交易日分钟槽位：09:30→0 ... 11:30→120，13:00→121 ... 15:00→240(共 241 槽)
const SESSION_MINUTES = 240
function minuteSlot(hhmm) {
  // hhmm 形如 "0930" / "1305"，也兼容 "09:30"
  const s = String(hhmm).replace(':', '')
  const h = parseInt(s.slice(0, 2), 10)
  const m = parseInt(s.slice(2, 4), 10)
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  const mins = h * 60 + m
  const open1 = 9 * 60 + 30   // 09:30
  const noon = 11 * 60 + 30   // 11:30
  const open2 = 13 * 60       // 13:00
  const close = 15 * 60       // 15:00
  if (mins <= open1) return 0
  if (mins <= noon) return mins - open1
  if (mins < open2) return noon - open1            // 午休并到 120
  if (mins <= close) return (noon - open1) + (mins - open2)
  return SESSION_MINUTES
}

function drawChart() {
  if (!canvas.value || !props.data || props.data.length < 2) return

  const ctx = canvas.value.getContext('2d')
  const data = props.data

  // HiDPI：物理像素 = 逻辑尺寸 × dpr，再整体缩放，避免高分屏发糊
  const dpr = window.devicePixelRatio || 1
  if (canvas.value.width !== Math.round(props.width * dpr) ||
      canvas.value.height !== Math.round(props.height * dpr)) {
    canvas.value.width = Math.round(props.width * dpr)
    canvas.value.height = Math.round(props.height * dpr)
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, props.width, props.height)

  const closes = data.map(d => d.close)
  // 基准价：优先昨收，否则用首点。用于着色 + 基准线，并纳入纵轴范围。
  const base = props.preClose != null && Number.isFinite(props.preClose)
    ? props.preClose
    : closes[0]
  const min = Math.min(...closes, base)
  const max = Math.max(...closes, base)
  const range = max - min || 1

  // 颜色：相对昨收的涨跌
  const last = closes[closes.length - 1]
  const isDown = props.color === 'green' || (!props.color && last < base)
  const lineColor = isDown ? '#16a34a' : '#dc2626'
  const fillTop = isDown ? 'rgba(34, 197, 94, 0.22)' : 'rgba(239, 68, 68, 0.22)'

  const padding = 2
  const chartWidth = props.width - padding * 2
  const chartHeight = props.height - padding * 2

  // X 坐标：分时模式按交易日分钟定位(固定满日宽度)，否则等距铺满
  const xAt = (d, i) => {
    if (props.intraday) {
      const slot = minuteSlot(d.datetime ?? d.time)
      if (slot != null) return padding + (slot / SESSION_MINUTES) * chartWidth
    }
    return padding + (i / (data.length - 1)) * chartWidth
  }
  const yAt = (c) => padding + chartHeight - ((c - min) / range) * chartHeight

  // 基准线(昨收) —— 一条淡淡的水平虚线
  const baseY = yAt(base)
  ctx.save()
  ctx.beginPath()
  ctx.setLineDash([2, 2])
  ctx.moveTo(padding, baseY)
  ctx.lineTo(padding + chartWidth, baseY)
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)'
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.restore()

  // 填充区域(线下到底)
  ctx.beginPath()
  data.forEach((d, i) => {
    const x = xAt(d, i)
    const y = yAt(d.close)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  const lastX = xAt(data[data.length - 1], data.length - 1)
  const firstX = xAt(data[0], 0)
  ctx.lineTo(lastX, padding + chartHeight)
  ctx.lineTo(firstX, padding + chartHeight)
  ctx.closePath()
  const grad = ctx.createLinearGradient(0, padding, 0, padding + chartHeight)
  grad.addColorStop(0, fillTop)
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = grad
  ctx.fill()

  // 折线
  ctx.beginPath()
  data.forEach((d, i) => {
    const x = xAt(d, i)
    const y = yAt(d.close)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.strokeStyle = lineColor
  ctx.lineWidth = 1.25
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.stroke()
}

watch(() => props.data, () => {
  drawChart()
}, { deep: true })
watch(() => [props.width, props.height, props.preClose], () => {
  drawChart()
})

onMounted(() => {
  drawChart()
})
</script>

<style scoped>
.mini-chart {
  display: flex;
  align-items: center;
  justify-content: center;
}

.mini-chart canvas {
  display: block;
}
</style>
