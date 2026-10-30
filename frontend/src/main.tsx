/**
 * React 入口。
 *
 * `bootstrap()` 必须在首次渲染之前执行：LegacyPage 的子 effect（真正调用页面模块模块）
 * 早于 App 的 effect 运行，若门面还没装好，settings 这类页面在渲染期读
 * `window.CPAuth.user` 就会直接抛错。
 */
import { bootstrap } from '@/app/bootstrap'
import { createRoot } from 'react-dom/client'
import App from './App'

bootstrap()

const host = document.getElementById('root')
if (!host) {
  throw new Error('缺少 #root 挂载点')
}

// 不用 StrictMode：它会把 effect 跑两遍，而 LegacyPage 的 effect 会重复调一次页面
// 加载函数（页面模块每次都发请求），等于凭空多一倍请求。
createRoot(host).render(<App />)
