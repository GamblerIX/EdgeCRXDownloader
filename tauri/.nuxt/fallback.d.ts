declare module '*.vue' {
  const component: unknown
  export default component
}

declare module '@tauri-apps/plugin-dialog' {
  export interface OpenDialogOptions {
    directory?: boolean
    multiple?: boolean
    title?: string
  }

  export function open(
    options?: OpenDialogOptions
  ): Promise<string | string[] | null>
}

declare function defineNuxtConfig<T>(config: T): T