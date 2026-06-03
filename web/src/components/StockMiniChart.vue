<template>
  <div class="mini-chart" ref="chartContainer">
    <canvas ref="canvas" :width="width" :height="height"></canvas>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'

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
  }
})

const canvas = ref(null)
const chartContainer = ref(null)

function drawChart() {
  if (!canvas.value || !props.data || props.data.length < 2) return
  
  const ctx = canvas.value.getContext('2d')
  const data = props.data
  
  // 清空画布
  ctx.clearRect(0, 0, props.width, props.height)
  
  // 提取收盘价
  const closes = data.map(d => d.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const range = max - min || 1
  
  // 计算颜色
  let lineColor = '#f87171'
  let fillColor = 'rgba(248, 113, 113, 0.15)'
  
  if (props.color === 'green') {
    lineColor = '#4ade80'
    fillColor = 'rgba(74, 222, 128, 0.15)'
  } else if (!props.color) {
    // 自动检测涨跌
    const first = closes[0]
    const last = closes[closes.length - 1]
    if (last < first) {
      lineColor = '#4ade80'
      fillColor = 'rgba(74, 222, 128, 0.15)'
    }
  }
  
  const padding = 2
  const chartWidth = props.width - padding * 2
  const chartHeight = props.height - padding * 2
  const stepX = chartWidth / (data.length - 1)
  
  // 创建路径
  ctx.beginPath()
  
  data.forEach((d, i) => {
    const x = padding + i * stepX
    const y = padding + chartHeight - ((d.close - min) / range) * chartHeight
    
    if (i === 0) {
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
    }
  })
  
  // 绘制填充区域
  const lastX = padding + (data.length - 1) * stepX
  const lastY = padding + chartHeight - ((closes[closes.length - 1] - min) / range) * chartHeight
  
  ctx.lineTo(lastX, padding + chartHeight)
  ctx.lineTo(padding, padding + chartHeight)
  ctx.closePath()
  
  ctx.fillStyle = fillColor
  ctx.fill()
  
  // 绘制折线
  ctx.beginPath()
  data.forEach((d, i) => {
    const x = padding + i * stepX
    const y = padding + chartHeight - ((d.close - min) / range) * chartHeight
    
    if (i === 0) {
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
    }
  })
  
  ctx.strokeStyle = lineColor
  ctx.lineWidth = 1.5
  ctx.stroke()
}

watch(() => props.data, () => {
  drawChart()
}, { deep: true })

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