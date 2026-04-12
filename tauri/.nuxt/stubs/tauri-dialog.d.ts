export interface OpenDialogOptions {
  directory?: boolean
  multiple?: boolean
  title?: string
}

export declare function open(
  options?: OpenDialogOptions
): Promise<string | string[] | null>