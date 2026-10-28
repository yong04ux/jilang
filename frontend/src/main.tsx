/**
 * S0 阶段：本文件只占位，证明「Vite 产物能落到后端认的路径」。
 * 页面此时仍由 index.html 里的一批旧脚本驱动（window.CP*）。
 * S2 起这里改为 createRoot(#root).render(<App />)，逐步接管渲染。
 */
const boot = () => {
  // 显式留痕，方便在控制台确认新入口确实加载了（S2 移除）
  document.documentElement.dataset.cpEntry = 'vite'
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true })
} else {
  boot()
}

export {}
