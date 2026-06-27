# Design

浅色专业投研工作台。白卡片 + 柔和浅灰底，蓝色 accent 只用于操作/选中态，红涨绿跌承担全部行情语义色。克制现代、中密度（Linear 式 SaaS 而非终端式高密度）。

## Theme

- 单一浅色主题（不做暗色切换）。
- 底色 `--bg-base: #f5f7fa`（冷灰，向品牌蓝微倾），卡片纯白 `--bg-surface: #ffffff`。
- 个股详情页与全站同主题，不允许单页走深色。

## Color Palette

| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#f5f7fa` | 页面底 |
| `--bg-surface` | `#ffffff` | 卡片/面板/侧栏/顶栏 |
| `--bg-hover` | `#eef2f7` | 悬停底 |
| `--bg-active` | `#e3eaf3` | 按下/选中底 |
| `--border` | `#e2e8f0` | 默认描边 |
| `--border-light` | `#cbd5e1` | 强描边/滚动条 |
| `--text-1` | `#1e293b` | 主文字 |
| `--text-2` | `#475569` | 次文字（正文级，须过 AA） |
| `--text-3` | `#64748b` | 辅助文字/标签 |
| `--accent` | `#2563eb` | 主操作、当前选中、焦点环；不作装饰 |
| `--up` / `--profit` | `#dc2626` | 涨/盈（A 股红涨，不可反转） |
| `--down` / `--loss` | `#16a34a` | 跌/亏 |
| `--success` | `#16a34a` | 成功态 |
| `--danger` | `#dc2626` | 错误态 |
| `--warning` | `#d97706` | 警告态 |

涨跌数字必须带 +/- 符号，不允许只用颜色区分。

## Typography

- 单一字族：系统栈 `-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif`；数字/代码用 `--font-mono`（JetBrains Mono 回退 Consolas）。
- 基准 14px；固定 rem 阶梯（非流式）：12 / 13 / 14 / 16 / 18 / 21 / 24。
- 表格数据 12–13px，正文 13–14px，页面标题 16–18px，指标大数 21–24px mono。
- 股票代码、价格、百分比一律 mono。

## Components

- **卡片/面板**：白底 + 1px `--border` + `--radius-xl(8px)` + `--shadow-card`；面板头 `panel-header`（标题左、动作/meta 右）。不嵌套卡片。
- **按钮**：`btn-primary`（蓝实底）/ `btn-ghost`（描边）两种为主；同一动作全站同一形态。
- **徽章**：`badge-{blue|green|red|amber|purple|cyan|gray}` 圆角胶囊。
- **表格**：`data-table`（sticky 表头、悬停行高亮）；移动端加 `responsive-table` + `data-label` 折叠成卡片。
- **表单**：`input` / `select-base` / `form-label`（11px 大写标签）。
- **加载**：列表/卡片用骨架屏；行内小操作才用 spinner。
- **空态**：`empty-state`，给出下一步指引而非"暂无数据"。
- **状态完整性**：交互组件必须有 default / hover / focus / active / disabled / loading / error。

## Layout

- 桌面：左侧栏（200px，可折叠到 52px）+ 顶栏（42px）+ 内容区；内容区页面自管 padding（建议 16–20px）。
- 移动（≤768px）：侧栏变抽屉、底部 5 项导航、表格折叠、触控目标 ≥44px、modal 变 bottom-sheet（`.sheet-on-mobile`）。
- 栅格：桌面声明列数 + `.grid-collapse` 系列在移动端折叠。

## Motion

- 150–250ms，`ease` / ease-out 曲线；只为状态变化服务（悬停、展开、toast），无装饰动画、无页面加载编排。
- `prefers-reduced-motion: reduce` 时退化为透明度淡入淡出。

## Charts (ECharts)

- 线/蜡烛图红涨绿跌；网格线 `--border` 级浅灰；tooltip 白底浅影。
- 图表容器固定高度防抖动，加载时显示骨架占位。
