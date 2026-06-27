// 共享 ECharts 注册：图表页局部 `import VChart from '../charts'` 使用，
// 不在 main.js 全局注册 —— 否则 echarts(~500KB) 会被打进首包，
// 而首页/登录页并不画图。模板里 <v-chart> 会解析到 VChart。
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import {
  LineChart, CandlestickChart, BarChart, TreemapChart, ScatterChart,
} from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, AxisPointerComponent,
  DataZoomComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
} from 'echarts/components'

use([
  CanvasRenderer,
  LineChart, CandlestickChart, BarChart, TreemapChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, AxisPointerComponent,
  DataZoomComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
])

export default VChart
