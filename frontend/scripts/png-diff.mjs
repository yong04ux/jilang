/**
 * PNG 像素级比对（无第三方依赖）
 *
 * 用来回答「两张截图到底差在哪、差多少」—— 元素几何与计算样式都一致却
 * 字节不同时，只能落到像素上。输出：差异像素数、差异占比、包围盒。
 *
 * 用法：node scripts/png-diff.mjs a.png b.png
 * 退出码 0 = 完全一致，1 = 有差异。
 */
import { readFileSync } from 'node:fs'
import { inflateSync } from 'node:zlib'

/** 解析 8 位 RGBA / RGB 的 PNG（Chromium 截图是 8 位 RGBA 或 RGB） */
function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('不是 PNG')
  let pos = 8
  let width = 0
  let height = 0
  let bitDepth = 0
  let colorType = 0
  const idat = []
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos)
    const type = buf.toString('ascii', pos + 4, pos + 8)
    const data = buf.subarray(pos + 8, pos + 8 + len)
    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      bitDepth = data[8]
      colorType = data[9]
      if (bitDepth !== 8) throw new Error(`只支持 8 位色深，实际 ${bitDepth}`)
      if (data[12] !== 0) throw new Error('不支持隔行扫描')
    } else if (type === 'IDAT') {
      idat.push(data)
    } else if (type === 'IEND') {
      break
    }
    pos += 12 + len
  }
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 0
  if (!channels) throw new Error(`不支持的色彩类型 ${colorType}`)
  const raw = inflateSync(Buffer.concat(idat))
  const stride = width * channels
  const out = Buffer.alloc(stride * height)

  // 逐行反滤波（PNG 的五种 filter）
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)]
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1))
    const cur = out.subarray(y * stride, (y + 1) * stride)
    const prev = y > 0 ? out.subarray((y - 1) * stride, y * stride) : null
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? cur[x - channels] : 0
      const b = prev ? prev[x] : 0
      const c = prev && x >= channels ? prev[x - channels] : 0
      let v = line[x]
      if (filter === 1) v += a
      else if (filter === 2) v += b
      else if (filter === 3) v += (a + b) >> 1
      else if (filter === 4) {
        const p = a + b - c
        const pa = Math.abs(p - a)
        const pb = Math.abs(p - b)
        const pc = Math.abs(p - c)
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c
      }
      cur[x] = v & 0xff
    }
  }
  return { width, height, channels, data: out }
}

const [aPath, bPath] = process.argv.slice(2)
if (!aPath || !bPath) {
  console.error('用法：node scripts/png-diff.mjs a.png b.png')
  process.exit(2)
}
const A = decodePng(readFileSync(aPath))
const B = decodePng(readFileSync(bPath))
if (A.width !== B.width || A.height !== B.height) {
  console.log(`尺寸不同：${A.width}x${A.height} vs ${B.width}x${B.height}`)
  process.exit(1)
}

let diff = 0
let maxDelta = 0
let minX = Infinity
let minY = Infinity
let maxX = -1
let maxY = -1
for (let y = 0; y < A.height; y++) {
  for (let x = 0; x < A.width; x++) {
    const ia = (y * A.width + x) * A.channels
    const ib = (y * B.width + x) * B.channels
    let d = 0
    for (let c = 0; c < Math.min(A.channels, B.channels); c++) {
      d = Math.max(d, Math.abs(A.data[ia + c] - B.data[ib + c]))
    }
    if (d > 0) {
      diff += 1
      if (d > maxDelta) maxDelta = d
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
  }
}

const total = A.width * A.height
const pct = ((diff / total) * 100).toFixed(4)
console.log(`尺寸 ${A.width}x${A.height}`)
if (diff === 0) {
  console.log('像素完全一致')
  process.exit(0)
}
console.log(`差异像素 ${diff} / ${total}（${pct}%），最大通道差 ${maxDelta}`)
console.log(`包围盒 x:${minX}-${maxX}  y:${minY}-${maxY}`)
process.exit(1)
