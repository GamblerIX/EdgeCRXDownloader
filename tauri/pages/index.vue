<script setup lang="ts">
import { Channel, invoke } from '@tauri-apps/api/core'
import { Effect, ProgressBarStatus, getCurrentWindow } from '@tauri-apps/api/window'
import { confirm, open } from '@tauri-apps/plugin-dialog'
import { useHead } from '#imports'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getUserFacingError } from '~/utils/error'
import {
  type DownloadInputPayload,
  extractExtensionId,
  formatBytes,
  formatPercent,
  parseExtensionInputs
} from '~/utils/extension'

type QueueStatus = 'waiting' | 'running' | 'success' | 'failed' | 'invalid'
type StatusTone = 'info' | 'success' | 'warning' | 'danger'
type ThemeMode = 'system' | 'light' | 'dark'
type ThemeTone = 'light' | 'dark'

interface QueueItem {
  lineNumber: number
  raw: string
  extensionId: string | null
  status: QueueStatus
  downloadedBytes: number
  totalBytes: number | null
  filePath: string | null
  error: string | null
}

interface DownloadOutcome {
  lineNumber: number
  extensionId: string
  filePath: string
  bytesWritten: number
}

interface DownloadFailure {
  lineNumber: number
  input: string
  reason: string
}

interface DownloadSummary {
  total: number
  successCount: number
  failureCount: number
  succeeded: DownloadOutcome[]
  failed: DownloadFailure[]
}

type DownloadEvent =
  | { type: 'batchStarted'; total: number }
  | {
      type: 'itemStarted'
      index: number
      total: number
      lineNumber: number
      extensionId: string
      fileName: string
    }
  | {
      type: 'itemProgress'
      index: number
      total: number
      lineNumber: number
      downloadedBytes: number
      totalBytes?: number | null
    }
  | {
      type: 'itemSucceeded'
      index: number
      total: number
      lineNumber: number
      extensionId: string
      filePath: string
      bytesWritten: number
    }
  | {
      type: 'itemFailed'
      index: number
      total: number
      lineNumber: number
      input: string
      reason: string
    }

interface SidebarMetric {
  label: string
  value: string
}

const sampleInput = [
  'iikmkjmpaadaobahmlepeloendndfphd',
  'https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN'
].join('\n')

const THEME_STORAGE_KEY = 'edge-crx-downloader.theme-mode'

const themeOptions: { value: ThemeMode; label: string }[] = [
  { value: 'system', label: '系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' }
]

const inputText = ref(sampleInput)
const saveDir = ref('')
const queue = ref<QueueItem[]>(buildQueueEntries(sampleInput))
const logs = ref<string[]>(['[准备] 选择保存目录后即可开始下载。'])
const summary = ref<DownloadSummary | null>(null)
const isRunning = ref(false)
const activeLine = ref<number | null>(null)
const statusTitle = ref('准备就绪')
const statusMessage = ref('输入扩展 ID 或 Edge 商店详情页 URL。')
const statusTone = ref<StatusTone>('info')
const logPanel = ref<HTMLElement | null>(null)
const themeMode = ref<ThemeMode>(readStoredTheme())
const systemTheme = ref<ThemeTone>(getSystemTheme())
const isDesktopShell = ref(false)
const isWindowFocused = ref(true)
const isWindowMaximized = ref(false)

let mediaQuery: MediaQueryList | null = null
let shellWindow: ReturnType<typeof getCurrentWindow> | null = null
let windowUnlisteners: Array<() => void> = []
let taskbarProgressSequence = 0
let taskbarProgressQueue = Promise.resolve()
let closePending = false

async function confirmAndClose(): Promise<boolean> {
  if (closePending) return false
  if (!isRunning.value) return true

  closePending = true
  try {
    const shouldClose = await confirm(
      '下载任务正在进行中，关闭窗口将丢失尚未完成的下载。\n确定要强制关闭吗？',
      { title: 'Edge CRX Downloader', kind: 'warning' }
    )
    if (shouldClose) isRunning.value = false
    return shouldClose
  } finally {
    closePending = false
  }
}

const resolvedTheme = computed<ThemeTone>(() => {
  return themeMode.value === 'system' ? systemTheme.value : themeMode.value
})

const queueStats = computed(() => {
  let valid = 0
  let waiting = 0
  let invalid = 0
  let running = 0
  let success = 0
  let failed = 0

  for (const item of queue.value) {
    if (item.extensionId) valid++
    switch (item.status) {
      case 'waiting': waiting++; break
      case 'running': running++; break
      case 'success': success++; break
      case 'failed': failed++; break
      case 'invalid': invalid++; failed++; break
    }
  }

  return { total: queue.value.length, valid, waiting, invalid, running, success, failed }
})

const canStart = computed(() => {
  return !isRunning.value && saveDir.value.trim().length > 0 && queueStats.value.valid > 0
})

const hasInput = computed(() => {
  return inputText.value.trim().length > 0
})

const totalWritten = computed(() => {
  if (summary.value) {
    return summary.value.succeeded.reduce(
      (total: number, item: DownloadOutcome) => total + item.bytesWritten,
      0
    )
  }

  return queue.value.reduce((total: number, item: QueueItem) => total + item.downloadedBytes, 0)
})

const successRate = computed(() => {
  const total = summary.value?.total ?? queueStats.value.total
  const success = summary.value?.successCount ?? queueStats.value.success

  if (total <= 0) {
    return '0%'
  }

  return `${Math.round((success / total) * 100)}%`
})

const sidebarMetrics = computed<SidebarMetric[]>(() => [
  {
    label: '队列总数',
    value: String(queueStats.value.total)
  },
  {
    label: '成功率',
    value: successRate.value
  },
  {
    label: '已写入',
    value: formatBytes(totalWritten.value)
  }
])

const queueStateCards = computed(() => {
  const s = queueStats.value
  return [
    { label: '等待', value: String(s.waiting), tone: 'neutral' },
    { label: '执行中', value: String(s.running), tone: 'info' },
    { label: '成功', value: String(s.success), tone: 'success' },
    { label: '异常', value: String(s.failed), tone: 'danger' }
  ]
})

const resultHeadline = computed(() => {
  if (isRunning.value) {
    return `正在执行 ${queueStats.value.valid} 项下载任务`
  }

  if (!summary.value) {
    return '等待首次执行'
  }

  if (summary.value.failureCount === 0) {
    return `本轮全部完成，共写入 ${summary.value.successCount} 个扩展`
  }

  if (summary.value.successCount === 0) {
    return '本轮未成功写入文件'
  }

  return `本轮完成 ${summary.value.successCount} / ${summary.value.total}，其余项需要处理`
})

const resultTone = computed<StatusTone>(() => {
  if (isRunning.value || !summary.value) {
    return 'info'
  }

  if (summary.value.failureCount === 0) {
    return 'success'
  }

  if (summary.value.successCount === 0) {
    return 'danger'
  }

  return 'warning'
})

const resultMessage = computed(() => {
  if (isRunning.value) {
    return `正在处理 ${queueStats.value.valid} 项可执行输入，日志与队列会持续更新。`
  }

  if (!summary.value) {
    return '执行完成后，这里会汇总成功文件和失败原因。'
  }

  if (summary.value.failureCount === 0) {
    return `本轮 ${summary.value.successCount} 项全部下载完成，结果已写入所选目录。`
  }

  if (summary.value.successCount === 0) {
    return `本轮 ${summary.value.failureCount} 项均失败，请根据失败原因修正后重试。`
  }

  return `本轮成功 ${summary.value.successCount} 项，失败 ${summary.value.failureCount} 项，可按失败原因逐项修正。`
})

useHead(() => ({
  title: 'Edge CRX Downloader',
  meta: [
    {
      name: 'theme-color',
      content: resolvedTheme.value === 'dark' ? '#11151c' : '#dbe5f0'
    }
  ]
}))

watch(inputText, () => {
  if (!isRunning.value) {
    queue.value = buildQueueEntries(inputText.value)
  }
})

watch(
  () => logs.value.length,
  async () => {
    await nextTick()
    if (logPanel.value) {
      logPanel.value.scrollTop = logPanel.value.scrollHeight
    }
  }
)

watch(
  themeMode,
  (value: ThemeMode) => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(THEME_STORAGE_KEY, value)
    }
  },
  { immediate: true }
)

watch(
  resolvedTheme,
  (value: ThemeTone) => {
    applyTheme(value)
    void applyNativeWindowSurface()
  },
  { immediate: true }
)

onMounted(() => {
  if (typeof window === 'undefined') {
    return
  }

  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  systemTheme.value = mediaQuery.matches ? 'dark' : 'light'
  mediaQuery.addEventListener('change', handleSystemThemeChange)

  void initializeNativeWindow()
})

onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }

  for (const unlisten of windowUnlisteners) {
    unlisten()
  }
  windowUnlisteners = []
})

function readStoredTheme(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'system'
  }

  const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (stored === 'system' || stored === 'light' || stored === 'dark') {
    return stored
  }

  return 'system'
}

function getSystemTheme(): ThemeTone {
  if (typeof window === 'undefined') {
    return 'dark'
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function handleSystemThemeChange() {
  systemTheme.value = getSystemTheme()
}

function applyTheme(theme: ThemeTone) {
  if (typeof document === 'undefined') {
    return
  }

  const root = document.documentElement
  root.dataset.theme = theme
  root.style.colorScheme = theme
}

async function initializeNativeWindow() {
  let currentWindow: ReturnType<typeof getCurrentWindow>

  try {
    currentWindow = getCurrentWindow()
  } catch {
    shellWindow = null
    isDesktopShell.value = false
    return
  }

  try {
    const [focused, maximized] = await Promise.all([
      currentWindow.isFocused(),
      currentWindow.isMaximized()
    ])

    shellWindow = currentWindow
    isDesktopShell.value = true
    isWindowFocused.value = focused
    isWindowMaximized.value = maximized
  } catch {
    shellWindow = null
    isDesktopShell.value = false
    return
  }

  await applyNativeWindowSurface()

  try {
    windowUnlisteners.push(
      await shellWindow.onResized(() => {
        void syncWindowState()
      })
    )
    windowUnlisteners.push(
      await shellWindow.onFocusChanged(({ payload }) => {
        isWindowFocused.value = payload
      })
    )
    windowUnlisteners.push(
      await shellWindow.onCloseRequested(async (event) => {
        if (!(await confirmAndClose())) {
          event.preventDefault()
        }
      })
    )
  } catch {
    reportShellIssue('窗口状态监听未启用，窗口焦点与尺寸标签可能不会实时更新。')
  }
}

async function syncWindowState() {
  if (!shellWindow) {
    return
  }

  try {
    const [focused, maximized] = await Promise.all([
      shellWindow.isFocused(),
      shellWindow.isMaximized()
    ])

    isWindowFocused.value = focused
    isWindowMaximized.value = maximized
  } catch {
    reportShellIssue('窗口状态探测失败，桌面壳指示信息可能不准确。')
  }
}

async function applyNativeWindowSurface() {
  if (!shellWindow) {
    return
  }

  try {
    await shellWindow.setShadow(true)
  } catch {
    reportShellIssue('窗口阴影应用失败，桌面壳外观将回退为标准窗口。')
  }

  const preferredEffects = [Effect.Mica, Effect.Acrylic]

  for (const effect of preferredEffects) {
    try {
      await shellWindow.setEffects({ effects: [effect] })
      return
    } catch {
      // Try the next supported material when the current one is unavailable.
    }
  }

  reportShellIssue('原生窗口材质不可用，已回退为标准窗口表面。')
}

async function updateTaskbarProgress(status: ProgressBarStatus, progress?: number) {
  const requestId = ++taskbarProgressSequence

  taskbarProgressQueue = taskbarProgressQueue.catch(() => undefined).then(async () => {
    if (!shellWindow || requestId !== taskbarProgressSequence) {
      return
    }

    try {
      await shellWindow.setProgressBar({
        status,
        ...(typeof progress === 'number' ? { progress } : {})
      })
    } catch {
      reportShellIssue('任务栏进度不可用，下载状态将只在应用内显示。')
    }
  })

  await taskbarProgressQueue
}

function calculateBatchProgress(index: number, total: number, itemFraction = 1) {
  if (total <= 0) {
    return 0
  }

  const clampedFraction = Math.max(0, Math.min(1, itemFraction))
  const finishedItems = Math.max(0, index - 1)

  return Math.max(1, Math.min(100, Math.round(((finishedItems + clampedFraction) / total) * 100)))
}

async function finalizeTaskbarProgress(result: DownloadSummary) {
  if (result.failureCount === 0) {
    await updateTaskbarProgress(ProgressBarStatus.None)
    return
  }

  if (result.successCount === 0) {
    await updateTaskbarProgress(ProgressBarStatus.Error, 100)
    return
  }

  await updateTaskbarProgress(ProgressBarStatus.Paused, 100)
}

async function minimizeWindow() {
  if (!shellWindow) {
    return
  }

  try {
    await shellWindow.minimize()
  } catch {
    reportShellIssue('最小化命令执行失败。')
  }
}

async function toggleWindowMaximize() {
  if (!shellWindow) {
    return
  }

  try {
    await shellWindow.toggleMaximize()
    await syncWindowState()
  } catch {
    reportShellIssue('最大化或还原命令执行失败。')
  }
}

async function closeWindow() {
  if (!shellWindow) {
    return
  }

  if (!(await confirmAndClose())) {
    return
  }

  try {
    await shellWindow.destroy()
  } catch {
    reportShellIssue('关闭命令执行失败。')
  }
}

let lastShellFault = ''

function reportShellIssue(message: string) {
  if (lastShellFault === message) {
    return
  }

  lastShellFault = message
  appendLog(`[窗口壳] ${message}`)
}

function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
}

function restoreSampleInput() {
  if (isRunning.value) {
    return
  }

  inputText.value = sampleInput
  summary.value = null
  setStatus('示例已载入', '已填入示例扩展 ID 与详情页地址。', 'info')
  appendLog('输入区已填入示例内容。')
}

function clearInput() {
  if (isRunning.value) {
    return
  }

  inputText.value = ''
  summary.value = null
  setStatus('输入已清空', '当前输入区已清空，可重新粘贴扩展 ID 或 URL。', 'info')
  appendLog('输入区已清空。')
}

function buildQueueEntries(source: string): QueueItem[] {
  return parseExtensionInputs(source).map((item: DownloadInputPayload) => {
    const extensionId = extractExtensionId(item.value)

    return {
      lineNumber: item.lineNumber,
      raw: item.value,
      extensionId,
      status: extensionId ? 'waiting' : 'invalid',
      downloadedBytes: 0,
      totalBytes: null,
      filePath: null,
      error: null
    }
  })
}

function setStatus(title: string, message: string, tone: StatusTone) {
  statusTitle.value = title
  statusMessage.value = message
  statusTone.value = tone
}

function appendLog(message: string) {
  const stamp = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  logs.value.push(`[${stamp}] ${message}`)
}

function findQueueItem(lineNumber: number) {
  return queue.value.find((item: QueueItem) => item.lineNumber === lineNumber) ?? null
}

function progressValue(item: QueueItem): number {
  if (item.status === 'success') {
    return 100
  }

  if (item.totalBytes && item.totalBytes > 0) {
    return Math.max(3, Math.min(100, (item.downloadedBytes / item.totalBytes) * 100))
  }

  if (item.status === 'running') {
    return item.downloadedBytes > 0 ? 28 : 8
  }

  return 0
}

function progressAriaValue(item: QueueItem) {
  if (item.status === 'success') {
    return 100
  }

  if (item.totalBytes && item.totalBytes > 0) {
    return Math.round(progressValue(item))
  }

  return undefined
}

function describeQueueProgress(item: QueueItem): string {
  if (item.status === 'success') {
    return `已完成，写入 ${formatBytes(item.downloadedBytes)}`
  }

  if (item.status === 'running') {
    if (item.totalBytes && item.totalBytes > 0) {
      return `已完成 ${formatPercent(item.downloadedBytes, item.totalBytes)}，${formatBytes(item.downloadedBytes)} / ${formatBytes(item.totalBytes)}`
    }

    return `正在下载，已写入 ${formatBytes(item.downloadedBytes)}，总大小未知`
  }

  if (item.status === 'failed' || item.status === 'invalid') {
    return item.error ?? '处理失败'
  }

  return item.extensionId ? '等待下载' : '输入无效，等待修正'
}

function describeQueueItem(item: QueueItem): string {
  if (item.status === 'success') {
    return `${formatBytes(item.downloadedBytes)} 已写入`
  }

  if (item.status === 'running') {
    return `${formatBytes(item.downloadedBytes)} / ${item.totalBytes ? formatBytes(item.totalBytes) : '未知大小'}`
  }

  if (item.status === 'failed' || item.status === 'invalid') {
    return item.error ?? '处理失败'
  }

  return item.extensionId ? `扩展 ID: ${item.extensionId}` : '将被标记为无效输入'
}

function formatQueueStatus(status: QueueStatus): string {
  switch (status) {
    case 'waiting':
      return '等待'
    case 'running':
      return '下载中'
    case 'success':
      return '完成'
    case 'failed':
      return '失败'
    case 'invalid':
      return '无效'
  }
}

function applyEvent(event: DownloadEvent) {
  switch (event.type) {
    case 'batchStarted':
      appendLog(`开始执行，共 ${event.total} 项。`)
      setStatus('执行中', `下载队列已启动，共 ${event.total} 条输入。`, 'info')
      void updateTaskbarProgress(ProgressBarStatus.Normal, 2)
      break

    case 'itemStarted': {
      const item = findQueueItem(event.lineNumber)
      activeLine.value = event.lineNumber
      if (item) {
        item.status = 'running'
        item.extensionId = event.extensionId
        item.error = null
      }
      appendLog(`第 ${event.lineNumber} 行开始下载 ${event.extensionId}。`)
      void updateTaskbarProgress(
        ProgressBarStatus.Normal,
        calculateBatchProgress(event.index, event.total, 0.02)
      )
      break
    }

    case 'itemProgress': {
      const item = findQueueItem(event.lineNumber)
      if (item) {
        item.status = 'running'
        item.downloadedBytes = event.downloadedBytes
        item.totalBytes = event.totalBytes ?? null
      }
      void updateTaskbarProgress(
        ProgressBarStatus.Normal,
        calculateBatchProgress(
          event.index,
          event.total,
          event.totalBytes && event.totalBytes > 0 ? event.downloadedBytes / event.totalBytes : 0.45
        )
      )
      break
    }

    case 'itemSucceeded': {
      const item = findQueueItem(event.lineNumber)
      if (item) {
        item.status = 'success'
        item.extensionId = event.extensionId
        item.downloadedBytes = event.bytesWritten
        item.totalBytes = event.bytesWritten
        item.filePath = event.filePath
        item.error = null
      }
      appendLog(`第 ${event.lineNumber} 行已完成，输出到 ${event.filePath}。`)
      void updateTaskbarProgress(
        ProgressBarStatus.Normal,
        calculateBatchProgress(event.index, event.total, 1)
      )
      break
    }

    case 'itemFailed': {
      const item = findQueueItem(event.lineNumber)
      if (item) {
        item.status = item.extensionId ? 'failed' : 'invalid'
        item.error = event.reason
      }
      appendLog(`第 ${event.lineNumber} 行失败：${event.reason}`)
      void updateTaskbarProgress(
        ProgressBarStatus.Paused,
        calculateBatchProgress(event.index, event.total, 1)
      )
      break
    }
  }
}

async function chooseDirectory() {
  if (isRunning.value) {
    return
  }

  try {
    const selected = await open({
      directory: true,
      multiple: false,
      title: '选择 CRX 保存目录'
    })

    if (typeof selected === 'string' && selected.trim()) {
      saveDir.value = selected
      setStatus('目录已就绪', `输出目录已设置为 ${selected}`, 'info')
      appendLog(`保存目录已更新为 ${selected}`)
    }
  } catch (error) {
    const message = getUserFacingError(error)
    setStatus('目录选择失败', message, 'danger')
    appendLog(message)
  }
}

async function startDownload() {
  if (isRunning.value) {
    return
  }

  const inputs = parseExtensionInputs(inputText.value)

  if (inputs.length === 0) {
    setStatus('缺少输入', '至少填写一条扩展 ID 或商店详情页 URL。', 'danger')
    appendLog('开始下载被拒绝：输入为空。')
    return
  }

  if (!saveDir.value.trim()) {
    setStatus('缺少目录', '请先选择 CRX 保存目录。', 'danger')
    appendLog('开始下载被拒绝：未选择保存目录。')
    return
  }

  queue.value = buildQueueEntries(inputText.value)
  summary.value = null
  isRunning.value = true
  activeLine.value = null

  setStatus('准备执行', `即将处理 ${inputs.length} 条输入。`, 'info')
  appendLog(`队列已锁定，共 ${inputs.length} 项，输出目录：${saveDir.value}`)

  const progress = new Channel<DownloadEvent>()
  progress.onmessage = (message: DownloadEvent) => {
    applyEvent(message)
  }

  try {
    const result = await invoke<DownloadSummary>('download_extensions', {
      inputs,
      saveDir: saveDir.value,
      progress
    })

    summary.value = result

    if (result.failureCount === 0) {
      setStatus('下载完成', `成功写入 ${result.successCount} 个 CRX 文件。`, 'success')
    } else if (result.successCount === 0) {
      setStatus('执行失败', `全部 ${result.failureCount} 项均未完成。`, 'danger')
    } else {
      setStatus(
        '部分完成',
        `成功 ${result.successCount} 项，失败 ${result.failureCount} 项。`,
        'warning'
      )
    }

    appendLog(
      `任务结束：成功 ${result.successCount} 项，失败 ${result.failureCount} 项，总写入 ${formatBytes(totalWritten.value)}。`
    )
    void finalizeTaskbarProgress(result)
  } catch (error) {
    const message = getUserFacingError(error)
    setStatus('执行异常', message, 'danger')
    appendLog(message)
    void updateTaskbarProgress(ProgressBarStatus.Error, 100)
  } finally {
    isRunning.value = false
    activeLine.value = null
  }
}
</script>


<template>
  <div
    class="window-shell"
    :data-focused="isWindowFocused"
  >
    <header
      class="titlebar"
      :data-tauri-drag-region="isDesktopShell ? '' : null"
    >
      <span
        class="titlebar-label"
        :data-tauri-drag-region="isDesktopShell ? '' : null"
      >Edge CRX Downloader</span>
      <div v-if="isDesktopShell" class="window-controls">
        <button
          class="focus-ring window-btn window-btn-minimize"
          type="button"
          aria-label="最小化窗口"
          @click.stop="minimizeWindow"
        >
          <span class="window-btn-icon" aria-hidden="true" />
        </button>
        <button
          class="focus-ring window-btn"
          :class="isWindowMaximized ? 'window-btn-restore' : 'window-btn-maximize'"
          type="button"
          :aria-label="isWindowMaximized ? '还原窗口' : '最大化窗口'"
          @click.stop="toggleWindowMaximize"
        >
          <span class="window-btn-icon" aria-hidden="true" />
        </button>
        <button
          class="focus-ring window-btn window-btn-close"
          type="button"
          aria-label="关闭窗口"
          @click.stop="closeWindow"
        >
          <span class="window-btn-icon" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div class="app-body">
      <aside class="sidebar">
        <div class="sidebar-group">
          <div class="theme-row" role="group" aria-label="主题切换">
            <button
              v-for="opt in themeOptions"
              :key="opt.value"
              class="focus-ring theme-chip"
              type="button"
              :data-active="themeMode === opt.value"
              :aria-pressed="themeMode === opt.value"
              @click="setThemeMode(opt.value)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>

        <div class="sidebar-group sidebar-metrics">
          <div v-for="metric in sidebarMetrics" :key="metric.label" class="metric-row">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>

        <div
          class="sidebar-group sidebar-status"
          role="status"
          aria-live="polite"
          :data-tone="statusTone"
          :aria-busy="isRunning"
        >
          <strong>{{ statusTitle }}</strong>
          <p>{{ statusMessage }}</p>
        </div>
      </aside>

      <main class="workspace">
        <section id="input" class="card">
          <div class="card-toolbar">
            <h2>输入</h2>
            <div class="toolbar-pills">
              <span class="pill">{{ queueStats.valid }} 有效</span>
              <span v-if="queueStats.invalid > 0" class="pill pill-warn">
                {{ queueStats.invalid }} 无效
              </span>
            </div>
            <div class="toolbar-actions">
              <button
                class="focus-ring btn-sm"
                type="button"
                :disabled="isRunning"
                @click="restoreSampleInput"
              >
                示例
              </button>
              <button
                class="focus-ring btn-sm"
                type="button"
                :disabled="isRunning || !hasInput"
                @click="clearInput"
              >
                清空
              </button>
            </div>
          </div>

          <label class="visually-hidden" for="extension-input">扩展输入</label>
          <textarea
            id="extension-input"
            v-model="inputText"
            class="focus-ring mono input-area"
            :disabled="isRunning"
            placeholder="每行一个扩展 ID 或商店详情页 URL"
            spellcheck="false"
          />

          <div class="input-footer">
            <div class="dir-label mono">{{ saveDir || '未选择保存目录' }}</div>
            <div class="btn-row">
              <button
                class="focus-ring btn"
                type="button"
                :disabled="isRunning"
                @click="chooseDirectory"
              >
                选择目录
              </button>
              <button
                class="focus-ring btn btn-primary"
                type="button"
                :disabled="!canStart"
                @click="startDownload"
              >
                {{ isRunning ? '下载中...' : '开始下载' }}
              </button>
            </div>
          </div>
        </section>

        <section id="queue" class="card">
          <div class="card-toolbar">
            <h2>下载队列</h2>
            <div class="toolbar-pills">
              <span
                v-for="card in queueStateCards"
                :key="card.label"
                class="pill"
                :data-tone="card.tone"
              >
                {{ card.label }} {{ card.value }}
              </span>
            </div>
          </div>

          <div v-if="queue.length" class="queue-list">
            <article
              v-for="item in queue"
              :key="item.lineNumber"
              class="queue-item"
              :data-status="item.status"
              :data-active="activeLine === item.lineNumber"
            >
              <div class="queue-head">
                <span class="mono queue-ln">#{{ item.lineNumber }}</span>
                <strong class="queue-id">{{ item.extensionId || item.raw }}</strong>
                <span class="queue-badge">{{ formatQueueStatus(item.status) }}</span>
              </div>
              <div
                class="progress-track"
                role="progressbar"
                :aria-label="`第 ${item.lineNumber} 行下载进度`"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="progressAriaValue(item)"
                :aria-valuetext="describeQueueProgress(item)"
              >
                <span class="progress-fill" :style="{ width: `${progressValue(item)}%` }" />
              </div>
              <p class="queue-detail">{{ describeQueueItem(item) }}</p>
            </article>
          </div>

          <p v-else class="empty-hint">输入扩展 ID 后队列将显示在此处。</p>
        </section>

        <section id="results" class="card">
          <h2>执行日志</h2>
          <div
            ref="logPanel"
            class="log-panel mono"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            :aria-busy="isRunning"
          >
            <p v-for="(entry, idx) in logs" :key="idx">{{ entry }}</p>
          </div>
        </section>

        <section class="card">
          <h2>汇总结果</h2>
          <div
            class="summary-bar"
            :data-tone="resultTone"
            role="status"
            aria-live="polite"
            :aria-busy="isRunning"
          >
            <strong>{{ resultHeadline }}</strong>
            <p>{{ resultMessage }}</p>
          </div>

          <div class="stat-row">
            <div class="stat-cell">
              <span>成功</span>
              <strong>{{ summary?.successCount ?? queueStats.success }}</strong>
            </div>
            <div class="stat-cell">
              <span>失败</span>
              <strong>{{ summary?.failureCount ?? queueStats.failed }}</strong>
            </div>
            <div class="stat-cell">
              <span>写入</span>
              <strong>{{ formatBytes(totalWritten) }}</strong>
            </div>
          </div>

          <template v-if="summary?.succeeded?.length">
            <h3>成功文件</h3>
            <div class="result-list">
              <article
                v-for="item in summary.succeeded"
                :key="`${item.lineNumber}-${item.extensionId}`"
                class="result-item result-ok"
              >
                <h4>{{ item.extensionId }}</h4>
                <p class="mono">{{ item.filePath }}</p>
              </article>
            </div>
          </template>

          <template v-if="summary?.failed?.length">
            <h3>失败原因</h3>
            <div class="result-list">
              <article
                v-for="item in summary.failed"
                :key="`${item.lineNumber}-${item.input}`"
                class="result-item result-err"
              >
                <h4>第 {{ item.lineNumber }} 行失败</h4>
                <p>{{ item.reason }}</p>
              </article>
            </div>
          </template>

          <p v-if="!summary" class="empty-hint">
            执行完成后，这里会显示成功文件和失败原因。
          </p>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.window-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--surface-strong);
}

.titlebar {
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 8px;
  flex-shrink: 0;
  user-select: none;
}

.titlebar-label {
  flex: 1;
  padding: 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  transition: opacity 120ms ease;
}

.window-shell[data-focused='false'] .titlebar-label {
  opacity: 0.5;
}

.window-controls {
  display: flex;
}

.window-btn {
  position: relative;
  width: 46px;
  height: 32px;
  border: 0;
  background: transparent;
  color: var(--text);
  display: grid;
  place-items: center;
  border-radius: 6px;
  transition: background 120ms ease;
}

.window-btn:hover {
  background: var(--surface-soft);
}

.window-btn-close:hover {
  background: var(--danger);
  color: #fff;
}

.window-btn-icon {
  position: relative;
  width: 12px;
  height: 12px;
  display: block;
}

.window-btn-minimize .window-btn-icon::before {
  content: '';
  position: absolute;
  inset: auto 0 2px 0;
  height: 1.5px;
  background: currentColor;
}

.window-btn-maximize .window-btn-icon::before {
  content: '';
  position: absolute;
  inset: 0;
  border: 1.5px solid currentColor;
}

.window-btn-restore .window-btn-icon::before,
.window-btn-restore .window-btn-icon::after {
  content: '';
  position: absolute;
  display: block;
}

.window-btn-restore .window-btn-icon::before {
  top: 0;
  right: 0;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
  background: var(--surface-strong);
}

.window-btn-restore .window-btn-icon::after {
  left: 0;
  bottom: 0;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
}

.window-btn-close .window-btn-icon::before,
.window-btn-close .window-btn-icon::after {
  content: '';
  position: absolute;
  top: 5px;
  left: 0;
  width: 12px;
  height: 1.5px;
  background: currentColor;
}

.window-btn-close .window-btn-icon::before {
  transform: rotate(45deg);
}

.window-btn-close .window-btn-icon::after {
  transform: rotate(-45deg);
}

.app-body {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  flex: 1;
  overflow: hidden;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  overflow-y: auto;
  border-right: 1px solid var(--line);
}

.sidebar-group {
  padding: 10px 12px;
  border-radius: 8px;
}

.theme-row {
  display: flex;
  gap: 4px;
}

.theme-chip {
  flex: 1;
  padding: 6px 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  text-align: center;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease;
}

.theme-chip:hover {
  background: var(--surface-soft);
}

.theme-chip[data-active='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.sidebar-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.metric-row span {
  color: var(--text-muted);
}

.metric-row strong {
  font-size: 14px;
}

.sidebar-status {
  border-left: 3px solid var(--accent);
  padding-left: 10px;
}

.sidebar-status[data-tone='success'] {
  border-left-color: var(--good);
}

.sidebar-status[data-tone='warning'] {
  border-left-color: var(--warn);
}

.sidebar-status[data-tone='danger'] {
  border-left-color: var(--danger);
}

.sidebar-status strong {
  display: block;
  font-size: 13px;
}

.sidebar-status p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.workspace {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  overflow-y: auto;
}

.card {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.card h2 {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 600;
}

.card h3 {
  margin: 12px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.card-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.card-toolbar h2 {
  margin: 0;
  flex-shrink: 0;
}

.toolbar-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.toolbar-actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.pill {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  color: var(--text-muted);
}

.pill[data-tone='info'] {
  color: var(--accent);
  border-color: var(--accent-ring);
}

.pill[data-tone='success'] {
  color: var(--good);
  border-color: var(--good-ring);
}

.pill[data-tone='danger'] {
  color: var(--danger);
  border-color: var(--danger-ring);
}

.pill-warn {
  color: var(--warn);
  border-color: var(--warn-ring);
}

.btn-sm {
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms ease;
}

.btn-sm:hover:not(:disabled) {
  background: var(--surface-soft);
}

.btn-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn {
  padding: 8px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface-soft);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  transition: background 120ms ease;
}

.btn:hover:not(:disabled) {
  background: var(--surface-elevated);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  border: none;
  background: var(--accent);
  color: var(--accent-text);
  font-weight: 600;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-strong);
}

.input-area {
  width: 100%;
  min-height: 160px;
  resize: vertical;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-elevated);
  font-size: 13px;
  line-height: 1.6;
}

.input-area::placeholder {
  color: var(--text-muted-soft);
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.dir-label {
  flex: 1 1 200px;
  padding: 8px 10px;
  background: var(--surface-soft);
  border-radius: 6px;
  border: 1px solid var(--line);
  font-size: 12px;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.btn-row {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.queue-item {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft);
  transition: border-color 120ms ease;
}

.queue-item[data-active='true'] {
  border-color: var(--accent);
}

.queue-item[data-status='success'] {
  border-color: var(--good-ring);
}

.queue-item[data-status='failed'],
.queue-item[data-status='invalid'] {
  border-color: var(--danger-ring);
}

.queue-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.queue-ln {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.queue-id {
  flex: 1;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.queue-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--line);
  background: var(--surface-elevated);
  flex-shrink: 0;
}

.queue-item[data-status='success'] .queue-badge {
  color: var(--good);
}

.queue-item[data-status='failed'] .queue-badge,
.queue-item[data-status='invalid'] .queue-badge {
  color: var(--danger);
}

.progress-track {
  height: 4px;
  margin: 8px 0 6px;
  border-radius: 2px;
  background: rgba(95, 107, 122, 0.15);
  overflow: hidden;
}

.progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 200ms ease;
}

.queue-detail {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.empty-hint {
  margin: 0;
  padding: 20px 0;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
}

.log-panel {
  min-height: 140px;
  max-height: 300px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-elevated);
  font-size: 12px;
}

.log-panel p {
  margin: 0 0 4px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.summary-bar {
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  margin-bottom: 10px;
}

.summary-bar[data-tone='info'] {
  border-color: var(--accent-ring);
}

.summary-bar[data-tone='success'] {
  border-color: var(--good-ring);
}

.summary-bar[data-tone='warning'] {
  border-color: var(--warn-ring);
}

.summary-bar[data-tone='danger'] {
  border-color: var(--danger-ring);
}

.summary-bar strong {
  display: block;
  font-size: 14px;
}

.summary-bar p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

.stat-cell {
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft);
  text-align: center;
}

.stat-cell span {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
}

.stat-cell strong {
  display: block;
  margin-top: 4px;
  font-size: 18px;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.result-item {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft);
}

.result-item h4 {
  margin: 0;
  font-size: 13px;
}

.result-item p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.result-ok {
  border-color: var(--good-ring);
}

.result-err {
  border-color: var(--danger-ring);
}

@media (max-width: 760px) {
  .app-body {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: none;
    border-bottom: 1px solid var(--line);
    flex-direction: row;
    flex-wrap: wrap;
    overflow-y: visible;
  }

  .sidebar-group {
    flex: 1;
    min-width: 140px;
  }

  .stat-row {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}
</style>
