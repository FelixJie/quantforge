// 研报正文清洗：把 PDF 抽取出的「裸文本」整理成可读的段落结构。
//
// PDF 抽取（fitz/pdfplumber）的文本有四类典型噪声，直接 <pre> 显示会很乱：
//   1. 对角水印被逐字抽出并反复出现（如「卡思优派产业研究院所有」整页重复）；
//   2. 页眉/页脚/免责声明逐页重复（「请务必阅读正文之后的免责声明部分」「1 / 3」）；
//   3. 正文按 PDF 行宽硬换行，一句话被切成多行；
//   4. 头部数据块标签与数值分两行（「当前股价（元）」/「51.56」）。
//
// 这里用纯前端启发式把它们整理成 {type:'h'|'p', text} 段落数组。
// 解析失败/过度清洗时上层仍保留「打开 PDF 原文」兜底，所以宁可保守。

// 句末终止标点：一行以此结尾，视为段落结束（PDF 里整段最后一行通常较短且以句号收尾）。
// 注意不含右括号 ）)：研报头部标签常以「（元）」「（亿元）」收尾，那是标签不是句末。
const TERM = /[。！？!?；;”’…]\s*$/

// 列表/编号行起始：应另起一段（含研报常用小节符号 ▌▍■◆等）。
const BULLET = /^(\d+[、.)）]|[（(][一二三四五六七八九十\d]+[）)]|[一二三四五六七八九十]+[、.]|[•·▪◦●▌▍▎■◆◇])/

// 小标题关键词（常见研报章节）。
const HEAD_KW = /^(投资要点|投资建议|核心观点|风险提示|盈利预测(与估值)?|事件(描述|点评)?|点评|要点|摘要|正文|目录|结论|催化剂|估值|公司简介|行业概况|业绩(回顾|综述)?)[:：]?$/

// 纯噪声行（页码 / 免责声明 / 资料来源单独成行等）。
const NOISE_RE = [
  /^[-—–\s]*\d+\s*[/／]\s*\d+[-—–\s]*$/,            // 1 / 3
  /^第?\s*\d+\s*页(\s*[/／]\s*共?\s*\d+\s*页)?$/,    // 第3页 / 共10页
  /^[-–—]\s*\d+\s*[-–—]$/,                          // - 12 -
  /请务必阅读.*免责声明/,
  /^[一-龥]{2,6}证券研究所?$/,              // XX证券研究所（单独成行的页眉）
]

// 头部数据块的「数值行」：纯数字 / 区间 / 百分比 / 带单位。
const VALUE_LINE = /^[+\-]?[\d,]+(\.\d+)?\s*([%~％]|万|亿|元|股|倍|个|[~～][\d,.]+)*\s*$|^[\d,.]+\s*[-~～/／]\s*[\d,.]+$/

function isHeading(line) {
  if (line.length > 20 || TERM.test(line)) return false
  if (HEAD_KW.test(line)) return true
  // 形如「一、xxx」「（一）xxx」「1. xxx」且较短
  if (/^([一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）)/.test(line) && line.length <= 20) return true
  return false
}

/**
 * @param {string} raw 抽取的研报纯文本
 * @returns {{type:'h'|'p', text:string}[]} 整理后的段落
 */
export function cleanReportText(raw) {
  if (!raw || typeof raw !== 'string') return []

  let lines = raw.replace(/\r/g, '').split('\n').map((s) => s.trim())

  // 统计行频：高频短行多为水印/页眉页脚（正常小标题不会重复 4 次以上）。
  const freq = Object.create(null)
  for (const l of lines) if (l) freq[l] = (freq[l] || 0) + 1

  const isNoise = (l) => {
    if (!l) return true
    if (freq[l] >= 4 && l.length <= 30) return true
    return NOISE_RE.some((re) => re.test(l))
  }
  lines = lines.filter((l) => !isNoise(l))

  // 头部数据块：把「标签行 + 紧邻数值行」合并成「标签：数值」。
  const merged = []
  for (let i = 0; i < lines.length; i++) {
    const cur = lines[i]
    const next = lines[i + 1]
    const curIsLabel = cur.length <= 16 && !TERM.test(cur) && !VALUE_LINE.test(cur)
    if (curIsLabel && next && VALUE_LINE.test(next)) {
      merged.push(`${cur.replace(/[:：]$/, '')}：${next}`)
      i++ // 跳过数值行
    } else {
      merged.push(cur)
    }
  }

  // 合并硬换行成段落。
  const paras = []
  let buf = ''
  const flush = () => { if (buf) { paras.push({ type: 'p', text: buf }); buf = '' } }

  for (const line of merged) {
    if (isHeading(line)) {
      flush()
      paras.push({ type: 'h', text: line })
      continue
    }
    if (BULLET.test(line) && buf) flush()  // 列表项另起一段
    buf += line
    if (TERM.test(line)) flush()           // 句末换行 = 段落结束
  }
  flush()

  // 垃圾守卫：纯水印/抽取失败的 PDF 往往只剩零碎无标点的短串，
  // 此时返回空，让上层回退到「打开 PDF 原文」而非显示乱码。
  const totalChars = paras.reduce((n, p) => n + p.text.length, 0)
  const hasSentence = paras.some((p) => p.type === 'h' || /[。！？!?]/.test(p.text))
  if (totalChars < 60 && !hasSentence) return []

  return paras
}
