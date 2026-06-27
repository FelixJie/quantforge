import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,            // 监听 0.0.0.0,127.0.0.1 / 局域网IP / ::1 都能访问
    port: 80,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',   // 强制走 IPv4,避开 Node 把 localhost 解析成 ::1 的坑
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
