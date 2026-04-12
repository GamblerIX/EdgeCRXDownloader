export interface TauriChannel<T = unknown> {
  onmessage?: (message: T) => void
}

export declare const Channel: {
  new <T = unknown>(): TauriChannel<T>
}

export declare function invoke<T = unknown>(
  command: string,
  args?: Record<string, unknown>
): Promise<T>