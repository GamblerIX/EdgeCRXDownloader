export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  devtools: { enabled: true },
  ssr: false,
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: 'Edge CRX Downloader',
      meta: [
        {
          name: 'description',
          content:
            'Desktop downloader for Microsoft Edge extension CRX files, powered by Nuxt and Tauri.'
        }
      ]
    }
  },
  devServer: {
    host: '0'
  },
  vite: {
    clearScreen: false,
    envPrefix: ['VITE_', 'TAURI_'],
    server: {
      strictPort: true
    }
  },
  ignore: ['**/src-tauri/**'],
  nitro: {
    preset: 'static'
  }
})
