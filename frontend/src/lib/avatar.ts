/** 头像：浏览器端裁成 128px 方图再传，避免原图几 MB 进数据库。 */
import { api } from '@/lib/api'
import { loadMe } from '@/stores/authStore'

export function shrinkAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const size = 128
      const canvas = document.createElement('canvas')
      canvas.width = size
      canvas.height = size
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        reject(new Error('canvas'))
        return
      }
      const scale = Math.max(size / img.width, size / img.height)
      const width = img.width * scale
      const height = img.height * scale
      ctx.drawImage(img, (size - width) / 2, (size - height) / 2, width, height)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', 0.86))
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image'))
    }
    img.src = url
  })
}

export async function saveAvatar(file: File): Promise<void> {
  await api.put('/api/auth/avatar', { avatar: await shrinkAvatar(file) })
  await loadMe()
}

export async function clearAvatar(): Promise<void> {
  await api.put('/api/auth/avatar', { avatar: null })
  await loadMe()
}
