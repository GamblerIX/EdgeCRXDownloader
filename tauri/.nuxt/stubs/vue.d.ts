export interface Ref<T> {
  value: T
}

export interface ComputedRef<T> extends Readonly<Ref<T>> {}

export declare function ref<T>(value: T): Ref<T>
export declare function computed<T>(getter: () => T): ComputedRef<T>
export declare function watch<T>(
  source: Ref<T> | (() => T),
  callback: (value: T, oldValue: T | undefined) => void | Promise<void>,
  options?: {
    immediate?: boolean
  }
): void
export declare function nextTick(): Promise<void>
export declare function onMounted(callback: () => void): void
export declare function onBeforeUnmount(callback: () => void): void