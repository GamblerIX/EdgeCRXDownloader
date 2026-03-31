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
type SectionId = 'overview' | 'input' | 'queue' | 'results'
type NativeSurface = 'mica' | 'acrylic' | 'none'

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

interface NavItem {
  id: string
  index: string
  label: string
  hint: string
}

interface ThemeOption {
  value: ThemeMode
  label: string
  hint: string
}

interface SidebarMetric {
  label: string
  value: string
  hint: string
}

const sampleInput = [
  'iikmkjmpaadaobahmlepeloendndfphd',
  'https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN'
].join('\n')

const THEME_STORAGE_KEY = 'edge-crx-downloader.theme-mode'

const navItems: NavItem[] = [
  { id: 'overview', index: '01', label: '概览', hint: '状态与主题' },
  { id: 'input', index: '02', label: '输入', hint: '扩展 ID / URL' },
  { id: 'queue', index: '03', label: '队列', hint: '逐项处理' },
  { id: 'results', index: '04', label: '结果', hint: '日志与汇总' }
]

const themeOptions: ThemeOption[] = [
  { value: 'system', label: '系统', hint: '跟随 Windows' },
  { value: 'light', label: '浅色', hint: 'WinUI 明亮' },
  { value: 'dark', label: '深色', hint: '低干扰夜间' }
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
const activeSection = ref<SectionId>('overview')
const isDesktopShell = ref(false)
const isWindowFocused = ref(true)
const isWindowMaximized = ref(false)
const nativeSurface = ref<NativeSurface>('none')
const shellFault = ref('')

let mediaQuery: MediaQueryList | null = null
let sectionObserver: IntersectionObserver | null = null
let shellWindow: ReturnType<typeof getCurrentWindow> | null = null
let windowUnlisteners: Array<() => void> = []
let taskbarProgressSequence = 0
let taskbarProgressQueue = Promise.resolve()

const resolvedTheme = computed<ThemeTone>(() => {
  return themeMode.value === 'system' ? systemTheme.value : themeMode.value
})

const themeSummary = computed(() => {
  if (themeMode.value === 'system') {
    return `系统 · ${resolvedTheme.value === 'dark' ? '深色' : '浅色'}`
  }

  return themeMode.value === 'dark' ? '深色模式' : '浅色模式'
})

const queueStats = computed(() => {
  const total = queue.value.length
  const valid = queue.value.filter((item: QueueItem) => item.extensionId).length
  const invalid = queue.value.filter((item: QueueItem) => item.status === 'invalid').length
  const running = queue.value.filter((item: QueueItem) => item.status === 'running').length
  const success = queue.value.filter((item: QueueItem) => item.status === 'success').length
  const failed = queue.value.filter(
    (item: QueueItem) => item.status === 'failed' || item.status === 'invalid'
  ).length

  return { total, valid, invalid, running, success, failed }
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
    value: String(queueStats.value.total),
    hint: `${queueStats.value.valid} 项可执行`
  },
  {
    label: '成功率',
    value: successRate.value,
    hint: `${queueStats.value.success} 成功 / ${queueStats.value.failed} 失败`
  },
  {
    label: '已写入',
    value: formatBytes(totalWritten.value),
    hint: isRunning.value ? '任务正在执行' : '等待下一次处理'
  }
])

const queueStateCards = computed(() => {
  const waiting = queue.value.filter((item: QueueItem) => item.status === 'waiting').length
  const running = queue.value.filter((item: QueueItem) => item.status === 'running').length
  const success = queue.value.filter((item: QueueItem) => item.status === 'success').length
  const failed = queue.value.filter(
    (item: QueueItem) => item.status === 'failed' || item.status === 'invalid'
  ).length

  return [
    { label: '等待', value: String(waiting), tone: 'neutral' },
    { label: '执行中', value: String(running), tone: 'info' },
    { label: '成功', value: String(success), tone: 'success' },
    { label: '异常', value: String(failed), tone: 'danger' }
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

const commandSummary = computed(() => {
  if (isRunning.value) {
    return `正在处理 ${queueStats.value.valid} 项可执行输入，请等待本轮完成。`
  }

  if (!saveDir.value.trim()) {
    return '先选择输出目录，再启动批量下载。'
  }

  if (queueStats.value.valid === 0) {
    return '当前没有可执行的扩展 ID，请修正输入。'
  }

  if (queueStats.value.invalid > 0) {
    return `已识别 ${queueStats.value.valid} 项可执行，另有 ${queueStats.value.invalid} 项需要修正。`
  }

  return `当前 ${queueStats.value.valid} 项可执行，可以直接开始下载。`
})

const activeSectionLabel = computed(() => {
  return navItems.find((item: NavItem) => item.id === activeSection.value)?.label ?? '概览'
})

const shellModeLabel = computed(() => {
  if (shellFault.value) {
    return 'Windows 桌面壳 · 降级'
  }

  return isDesktopShell.value ? 'Windows 桌面壳' : '浏览器预览'
})

const shellMaterialLabel = computed(() => {
  if (!isDesktopShell.value) {
    return 'Web Canvas'
  }

  if (nativeSurface.value === 'mica') {
    return 'Mica 材质'
  }

  if (nativeSurface.value === 'acrylic') {
    return 'Acrylic 材质'
  }

  return '标准窗口表面'
})

const windowStateLabel = computed(() => {
  if (!isDesktopShell.value) {
    return '浏览器窗口'
  }

  return isWindowMaximized.value ? '已最大化' : '窗口模式'
})

const desktopStatusLabel = computed(() => {
  if (shellFault.value) {
    return '部分窗口功能不可用'
  }

  if (!isDesktopShell.value) {
    return '预览环境'
  }

  return isWindowFocused.value ? '当前前台窗口' : '后台窗口'
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
    void applyNativeWindowSurface(value)
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

  void nextTick().then(() => {
    observeSections()
  })
})

onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }

  if (sectionObserver) {
    sectionObserver.disconnect()
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

  await applyNativeWindowSurface(resolvedTheme.value)

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
        if (!isRunning.value) {
          return
        }

        event.preventDefault()

        const shouldClose = await confirm(
          '下载任务正在进行中，关闭窗口将丢失尚未完成的下载。\n确定要强制关闭吗？',
          { title: 'Edge CRX Downloader', kind: 'warning' }
        )

        if (shouldClose) {
          isRunning.value = false
          await shellWindow.close()
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

async function applyNativeWindowSurface(theme: ThemeTone) {
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
      nativeSurface.value = effect === Effect.Mica ? 'mica' : 'acrylic'
      return
    } catch {
      // Try the next supported material when the current one is unavailable.
    }
  }

  nativeSurface.value = 'none'
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

  if (isRunning.value) {
    const shouldClose = await confirm(
      '下载任务正在进行中，关闭窗口将丢失尚未完成的下载。\n确定要强制关闭吗？',
      { title: 'Edge CRX Downloader', kind: 'warning' }
    )

    if (!shouldClose) {
      return
    }

    isRunning.value = false
  }

  try {
    await shellWindow.close()
  } catch {
    reportShellIssue('关闭命令执行失败。')
  }
}

function reportShellIssue(message: string) {
  if (shellFault.value === message) {
    return
  }

  shellFault.value = message
  appendLog(`[窗口壳] ${message}`)
}

function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
}

function scrollToSection(sectionId: string) {
  if (typeof document === 'undefined') {
    return
  }

  activeSection.value = sectionId as SectionId
  const target = document.getElementById(sectionId)
  target?.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start'
  })
}

function prefersReducedMotion() {
  if (typeof window === 'undefined') {
    return false
  }

  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function observeSections() {
  if (typeof document === 'undefined' || typeof IntersectionObserver === 'undefined') {
    return
  }

  sectionObserver?.disconnect()
  sectionObserver = new IntersectionObserver(
    (entries) => {
      const visibleEntries = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => right.intersectionRatio - left.intersectionRatio)

      const currentEntry = visibleEntries[0]
      if (currentEntry?.target.id) {
        activeSection.value = currentEntry.target.id as SectionId
      }
    },
    {
      rootMargin: '-14% 0px -52% 0px',
      threshold: [0.1, 0.25, 0.45, 0.7]
    }
  )

  for (const item of navItems) {
    const target = document.getElementById(item.id)
    if (target) {
      sectionObserver.observe(target)
    }
  }
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
    :data-desktop="isDesktopShell"
    :data-focused="isWindowFocused"
    :data-maximized="isWindowMaximized"
  >
    <header class="window-titlebar">
      <div
        class="window-caption"
        :data-tauri-drag-region="isDesktopShell ? '' : null"
      >
        <div class="window-glyph" :data-tauri-drag-region="isDesktopShell ? '' : null">EC</div>
        <div class="window-copy">
          <strong :data-tauri-drag-region="isDesktopShell ? '' : null">Edge CRX Downloader</strong>
          <small :data-tauri-drag-region="isDesktopShell ? '' : null">
            {{ shellModeLabel }} · {{ shellMaterialLabel }}
          </small>
        </div>
      </div>

      <div
        class="window-caption-spacer"
        :data-tauri-drag-region="isDesktopShell ? '' : null"
        aria-hidden="true"
      />

      <div v-if="isDesktopShell" class="window-controls" aria-label="窗口控制区">
        <button
          class="focus-ring window-control window-control-minimize"
          type="button"
          aria-label="最小化窗口"
          @click.stop="minimizeWindow"
        >
          <span class="window-control-glyph" aria-hidden="true" />
        </button>
        <button
          class="focus-ring window-control"
          :class="isWindowMaximized ? 'window-control-restore' : 'window-control-maximize'"
          type="button"
          :aria-label="isWindowMaximized ? '还原窗口' : '最大化窗口'"
          @click.stop="toggleWindowMaximize"
        >
          <span class="window-control-glyph" aria-hidden="true" />
        </button>
        <button
          class="focus-ring window-control window-control-close"
          type="button"
          aria-label="关闭窗口"
          @click.stop="closeWindow"
        >
          <span class="window-control-glyph" aria-hidden="true" />
        </button>
      </div>
    </header>

    <section class="commandbar">
      <div class="commandbar-actions">
        <button
          class="focus-ring button solid commandbar-button commandbar-button-primary"
          type="button"
          :disabled="!canStart"
          @click="startDownload"
        >
          <span class="commandbar-button-label">{{ isRunning ? '批量下载中' : '开始下载' }}</span>
          <small>{{ queueStats.valid }} 项可执行</small>
        </button>

        <button
          class="focus-ring button ghost commandbar-button"
          type="button"
          :disabled="isRunning"
          @click="chooseDirectory"
        >
          <span class="commandbar-button-label">选择目录</span>
          <small>{{ saveDir ? '输出目录已设置' : '指定 CRX 保存位置' }}</small>
        </button>

        <button
          class="focus-ring button ghost commandbar-button"
          type="button"
          :disabled="isRunning"
          @click="restoreSampleInput"
        >
          <span class="commandbar-button-label">填充示例</span>
          <small>快速验证下载流程</small>
        </button>

        <button
          class="focus-ring button ghost commandbar-button"
          type="button"
          @click="scrollToSection('results')"
        >
          <span class="commandbar-button-label">查看结果</span>
          <small>跳转到日志和汇总区</small>
        </button>
      </div>

      <div class="commandbar-info">
        <div class="commandbar-chip-row">
          <span class="commandbar-chip">{{ shellModeLabel }}</span>
          <span class="commandbar-chip">{{ shellMaterialLabel }}</span>
          <span class="commandbar-chip">{{ windowStateLabel }}</span>
          <span class="commandbar-chip" :data-tone="isWindowFocused ? 'success' : 'warning'">
            {{ desktopStatusLabel }}
          </span>
        </div>
        <p class="commandbar-note">{{ commandSummary }}</p>
        <p class="commandbar-path mono">{{ saveDir || '输出目录未设置' }}</p>
      </div>
    </section>

    <main class="app-shell">
    <aside class="sidebar">
      <section class="brand-card">
        <div class="brand-mark">EC</div>
        <div class="brand-copy-wrap">
          <p class="section-kicker">WinUI3 Tone</p>
          <h1>Edge CRX Downloader</h1>
          <p class="brand-copy">
            面向 Windows 10+ 的批量 CRX 下载控制台，采用更接近 WinUI3 的中性底色、侧边栏导航和可切换主题。
          </p>
        </div>
      </section>

      <section class="sidebar-card">
        <p class="section-kicker">Navigation</p>
        <nav class="sidebar-nav" aria-label="页面导航">
          <button
            v-for="item in navItems"
            :key="item.id"
            class="focus-ring sidebar-link"
            type="button"
            :data-active="activeSection === item.id"
            :aria-current="activeSection === item.id ? 'location' : undefined"
            @click="scrollToSection(item.id)"
          >
            <span class="sidebar-link-index">{{ item.index }}</span>
            <span class="sidebar-link-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.hint }}</small>
            </span>
          </button>
        </nav>
      </section>

      <section class="sidebar-card">
        <p class="section-kicker">Theme</p>
        <div class="segmented-control" role="group" aria-label="主题切换">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            class="focus-ring theme-option"
            type="button"
            :data-active="themeMode === option.value"
            :aria-pressed="themeMode === option.value"
            @click="setThemeMode(option.value)"
          >
            <span>{{ option.label }}</span>
            <small>{{ option.hint }}</small>
          </button>
        </div>
        <p class="sidebar-note">当前主题：{{ themeSummary }}</p>
      </section>

      <section class="sidebar-card quick-card">
        <p class="section-kicker">Quick Actions</p>
        <div class="quick-action-grid">
          <button
            class="focus-ring quick-action-button"
            type="button"
            :disabled="isRunning"
            @click="restoreSampleInput"
          >
            填充示例
          </button>
          <button
            class="focus-ring quick-action-button"
            type="button"
            :disabled="isRunning || !hasInput"
            @click="clearInput"
          >
            清空输入
          </button>
          <button
            class="focus-ring quick-action-button"
            type="button"
            @click="scrollToSection('results')"
          >
            查看结果
          </button>
        </div>
        <p class="sidebar-note">{{ commandSummary }}</p>
      </section>

      <section class="sidebar-card metrics-card">
        <article v-for="metric in sidebarMetrics" :key="metric.label" class="metric-tile">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.hint }}</small>
        </article>
      </section>

      <section
        class="sidebar-card status-card"
        role="status"
        aria-live="polite"
        :data-tone="statusTone"
        :aria-busy="isRunning"
      >
        <p class="section-kicker">Runtime Status</p>
        <h2>{{ statusTitle }}</h2>
        <p class="status-copy">{{ statusMessage }}</p>
        <div class="status-footer">
          <span class="status-pill" :data-tone="statusTone">
            {{ isRunning ? '执行中' : '待命' }}
          </span>
          <span class="mono">{{ successRate }} success</span>
        </div>
      </section>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="section-kicker">Desktop Workspace</p>
          <h2>WinUI3 风格的界面布局、系统主题和实时队列。</h2>
        </div>
        <div class="topbar-stack">
          <div class="topbar-rail">
            <span class="topbar-chip">{{ themeSummary }}</span>
            <span class="topbar-chip">当前区块 · {{ activeSectionLabel }}</span>
            <span class="topbar-chip" :data-tone="statusTone">
              {{ isRunning ? '执行中' : '已就绪' }}
            </span>
          </div>
          <p class="topbar-note">{{ commandSummary }}</p>
        </div>
      </header>

      <section id="overview" class="hero-card">
        <div class="hero-copy">
          <p class="eyebrow">Fluent-inspired</p>
          <h1>面向 Windows 10+ 的 Edge 扩展 CRX 批量下载器。</h1>
          <p class="hero-text">
            采用更接近 WinUI3 的中性底色、圆角卡片、Mica 质感和侧边栏导航，让这个桌面工具更像原生 Windows 应用。
          </p>
          <div class="hero-tags">
            <span class="hero-tag">侧边栏导航</span>
            <span class="hero-tag">系统主题</span>
            <span class="hero-tag">深色模式</span>
            <span class="hero-tag">实时进度</span>
          </div>
        </div>

        <div class="hero-stats">
          <article class="hero-stat">
            <span>队列总数</span>
            <strong>{{ queueStats.total }}</strong>
            <small>{{ queueStats.valid }} 项可执行，{{ queueStats.invalid }} 项待校验</small>
          </article>
          <article class="hero-stat">
            <span>成功率</span>
            <strong>{{ successRate }}</strong>
            <small>{{ queueStats.success }} 成功 / {{ queueStats.failed }} 失败</small>
          </article>
          <article class="hero-stat">
            <span>已写入</span>
            <strong>{{ formatBytes(totalWritten) }}</strong>
            <small>{{ isRunning ? '任务仍在执行' : '等待下一轮批量下载' }}</small>
          </article>
          <article class="hero-stat hero-stat-wide">
            <span>输出目录</span>
            <strong class="hero-directory mono">{{ saveDir || '尚未选择目录' }}</strong>
            <small>{{ resultHeadline }}</small>
          </article>
        </div>
      </section>

      <section class="content-grid">
        <article id="input" class="panel-card panel-input">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Input Deck</p>
              <h3>输入扩展 ID 或商店 URL</h3>
            </div>
            <span class="mono line-badge">{{ queueStats.total }} lines</span>
          </div>

          <div class="panel-toolbar">
            <div class="panel-pills">
              <span class="panel-pill" data-tone="accent">{{ queueStats.valid }} 项有效</span>
              <span
                class="panel-pill"
                :data-tone="queueStats.invalid > 0 ? 'warning' : 'success'"
              >
                {{ queueStats.invalid }} 项待修正
              </span>
              <span class="panel-pill" :data-tone="saveDir ? 'success' : 'neutral'">
                {{ saveDir ? '目录已选' : '未选目录' }}
              </span>
            </div>
            <div class="panel-tools">
              <button
                class="focus-ring mini-button"
                type="button"
                :disabled="isRunning"
                @click="restoreSampleInput"
              >
                示例
              </button>
              <button
                class="focus-ring mini-button"
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

          <div class="action-row">
            <div class="directory-chip">
              <span>保存目录</span>
              <strong class="mono">{{ saveDir || '尚未选择' }}</strong>
            </div>

            <div class="button-group">
              <button
                class="focus-ring button ghost"
                type="button"
                :disabled="isRunning"
                @click="chooseDirectory"
              >
                选择目录
              </button>
              <button
                class="focus-ring button solid"
                type="button"
                :disabled="!canStart"
                @click="startDownload"
              >
                {{ isRunning ? '下载中...' : '开始下载' }}
              </button>
            </div>
          </div>
        </article>

        <article id="queue" class="panel-card panel-queue">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Execution Queue</p>
              <h3>逐项处理状态</h3>
            </div>
            <span class="mono line-badge">{{ queueStats.running }} active</span>
          </div>

          <div class="queue-overview-grid">
            <article
              v-for="card in queueStateCards"
              :key="card.label"
              class="queue-overview-card"
              :data-tone="card.tone"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
            </article>
          </div>

          <div v-if="queue.length" class="queue-list">
            <article
              v-for="item in queue"
              :key="item.lineNumber"
              class="queue-item"
              :data-status="item.status"
              :data-active="activeLine === item.lineNumber"
            >
              <div class="queue-topline">
                <div>
                  <p class="mono queue-line">#{{ item.lineNumber }}</p>
                  <h4>{{ item.extensionId || item.raw }}</h4>
                </div>
                <span class="queue-state">{{ formatQueueStatus(item.status) }}</span>
              </div>

              <p class="queue-raw mono">{{ item.raw }}</p>

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

              <div class="queue-meta">
                <span>{{ describeQueueItem(item) }}</span>
                <span v-if="item.status === 'running'" class="mono">
                  {{ formatPercent(item.downloadedBytes, item.totalBytes) }}
                </span>
              </div>
            </article>
          </div>

          <div v-else class="empty-card">
            <h4>队列为空</h4>
            <p>先在左侧输入至少一条扩展 ID 或 Edge 商店详情页 URL。</p>
          </div>
        </article>
      </section>

      <section id="results" class="result-grid">
        <article class="panel-card">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Runtime Log</p>
              <h3>执行日志</h3>
            </div>
            <span class="mono line-badge">{{ logs.length }} entries</span>
          </div>

          <div
            ref="logPanel"
            class="log-console mono"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            :aria-busy="isRunning"
          >
            <p v-for="(entry, index) in logs" :key="`${index}-${entry}`">{{ entry }}</p>
          </div>
        </article>

        <article class="panel-card">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">Result Strip</p>
              <h3>汇总结果</h3>
            </div>
            <span class="mono line-badge">{{ summary?.total ?? queueStats.total }} total</span>
          </div>

          <div
            class="summary-banner"
            :data-tone="resultTone"
            role="status"
            aria-live="polite"
            :aria-busy="isRunning"
          >
            <span class="summary-banner-label">执行摘要</span>
            <strong>{{ resultHeadline }}</strong>
            <p>{{ resultMessage }}</p>
          </div>

          <div class="summary-grid">
            <div class="summary-card">
              <span>成功</span>
              <strong>{{ summary?.successCount ?? queueStats.success }}</strong>
            </div>
            <div class="summary-card">
              <span>失败</span>
              <strong>{{ summary?.failureCount ?? queueStats.failed }}</strong>
            </div>
            <div class="summary-card">
              <span>写入体积</span>
              <strong>{{ formatBytes(totalWritten) }}</strong>
            </div>
          </div>

          <p v-if="summary?.succeeded?.length" class="result-section-title">成功文件</p>
          <div v-if="summary?.succeeded?.length" class="result-list">
            <article
              v-for="item in summary.succeeded"
              :key="`${item.lineNumber}-${item.extensionId}`"
              class="result-item success"
            >
              <h4>{{ item.extensionId }}</h4>
              <p class="mono">{{ item.filePath }}</p>
            </article>
          </div>

          <p v-if="summary?.failed?.length" class="result-section-title">失败原因</p>
          <div v-if="summary?.failed?.length" class="result-list">
            <article
              v-for="item in summary.failed"
              :key="`${item.lineNumber}-${item.input}`"
              class="result-item failure"
            >
              <h4>第 {{ item.lineNumber }} 行失败</h4>
              <p>{{ item.reason }}</p>
            </article>
          </div>

          <div v-if="!summary" class="empty-card compact">
            <h4>等待首次执行</h4>
            <p>这里会显示每一轮下载的成功文件和失败原因。</p>
          </div>
        </article>
      </section>
    </section>
    </main>

    <footer class="window-statusbar">
      <span>Shell · {{ shellModeLabel }}</span>
      <span>材质 · {{ shellMaterialLabel }}</span>
      <span>窗口 · {{ windowStateLabel }}</span>
      <span>{{ statusTitle }}</span>
      <span class="mono">{{ saveDir || '输出目录未设置' }}</span>
    </footer>
  </div>
</template>

<style scoped>
.window-shell {
  width: min(1760px, calc(100% - 22px));
  margin: 10px auto;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 32px;
  background: color-mix(in srgb, var(--surface-strong) 86%, transparent);
  box-shadow: var(--shadow-strong);
  backdrop-filter: blur(32px) saturate(180%);
}

.window-shell[data-focused='false'] {
  border-color: var(--line-strong);
}

.window-shell[data-maximized='true'][data-desktop='true'] {
  width: 100%;
  min-height: 100vh;
  margin: 0;
  padding: 8px;
  border-radius: 0;
  border-left: 0;
  border-right: 0;
}

.window-titlebar,
.commandbar,
.window-statusbar {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--surface);
  box-shadow: var(--shadow);
  backdrop-filter: blur(26px) saturate(180%);
}

.window-titlebar {
  display: flex;
  align-items: stretch;
  gap: 10px;
  padding: 8px;
  margin-bottom: 14px;
}

.window-caption,
.window-caption-spacer {
  min-height: 46px;
  border-radius: 16px;
}

.window-caption {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
  user-select: none;
}

.window-caption-spacer {
  flex: 1 1 auto;
}

.window-glyph {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: var(--accent-text);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  background: linear-gradient(135deg, var(--accent), var(--accent-strong));
  box-shadow: 0 12px 26px var(--accent-shadow);
}

.window-copy {
  display: grid;
  gap: 2px;
}

.window-copy strong,
.commandbar-button-label {
  font-size: 14px;
  font-weight: 700;
}

.window-copy small,
.commandbar-note,
.commandbar-path,
.window-statusbar span,
.commandbar-chip,
.commandbar-button small {
  color: var(--text-muted);
}

.window-controls {
  display: flex;
  gap: 6px;
}

.window-control {
  position: relative;
  width: 46px;
  min-width: 46px;
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: var(--text);
  display: grid;
  place-items: center;
  transition:
    background 160ms ease,
    color 160ms ease;
}

.window-control:hover {
  background: var(--surface-soft);
}

.window-control:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.window-control:disabled:hover {
  background: transparent;
}

.window-control-close:hover {
  color: #ffffff;
  background: var(--danger);
}

.window-control-glyph {
  position: relative;
  width: 14px;
  height: 14px;
  display: block;
}

.window-control-minimize .window-control-glyph::before,
.window-control-maximize .window-control-glyph::before,
.window-control-close .window-control-glyph::before,
.window-control-close .window-control-glyph::after,
.window-control-restore .window-control-glyph::before,
.window-control-restore .window-control-glyph::after {
  content: '';
  position: absolute;
  display: block;
}

.window-control-minimize .window-control-glyph::before {
  inset: auto 1px 2px 1px;
  height: 1.5px;
  background: currentColor;
}

.window-control-maximize .window-control-glyph::before {
  inset: 1px;
  border: 1.5px solid currentColor;
}

.window-control-restore .window-control-glyph::before {
  top: 1px;
  right: 1px;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
  background: var(--surface);
}

.window-control-restore .window-control-glyph::after {
  left: 1px;
  bottom: 1px;
  width: 8px;
  height: 8px;
  border: 1.5px solid currentColor;
}

.window-control-close .window-control-glyph::before,
.window-control-close .window-control-glyph::after {
  top: 6px;
  left: 0;
  width: 14px;
  height: 1.5px;
  background: currentColor;
}

.window-control-close .window-control-glyph::before {
  transform: rotate(45deg);
}

.window-control-close .window-control-glyph::after {
  transform: rotate(-45deg);
}

.commandbar {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 18px;
  margin-bottom: 18px;
}

.commandbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.commandbar-button {
  display: grid;
  gap: 4px;
  min-width: 158px;
  text-align: left;
  align-content: center;
}

.commandbar-button-primary {
  min-width: 180px;
}

.button.solid.commandbar-button small {
  color: color-mix(in srgb, var(--accent-text) 78%, transparent);
}

.commandbar-info {
  min-width: 320px;
  display: grid;
  gap: 8px;
  justify-items: end;
  align-content: center;
}

.commandbar-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.commandbar-chip {
  padding: 7px 11px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.commandbar-chip[data-tone='success'] {
  color: var(--good);
  border-color: var(--good-ring);
}

.commandbar-chip[data-tone='warning'] {
  color: var(--warn);
  border-color: var(--warn-ring);
}

.commandbar-note,
.commandbar-path {
  margin: 0;
  text-align: right;
}

.commandbar-note {
  max-width: 540px;
  line-height: 1.5;
}

.commandbar-path {
  max-width: 540px;
  overflow-wrap: anywhere;
}

.app-shell {
  width: 100%;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

.sidebar {
  position: sticky;
  top: 20px;
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  background: var(--surface);
  box-shadow: var(--shadow);
  backdrop-filter: blur(24px) saturate(180%);
}

#overview,
#input,
#queue,
#results {
  scroll-margin-top: 24px;
}

.brand-card,
.sidebar-card,
.topbar,
.hero-card,
.panel-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-xl);
  background: var(--surface);
  box-shadow: var(--shadow);
  backdrop-filter: blur(24px) saturate(180%);
}

.brand-card {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 16px;
  padding: 18px;
  background:
    linear-gradient(180deg, var(--accent-soft), transparent 72%),
    var(--surface);
}

.brand-mark {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: var(--accent-text);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.04em;
  background: linear-gradient(135deg, var(--accent), var(--accent-strong));
  box-shadow: 0 18px 34px rgba(0, 103, 192, 0.28);
}

.brand-copy-wrap h1,
.topbar h2,
.hero-copy h1,
.panel-head h3,
.empty-card h4,
.queue-item h4,
.result-item h4,
.status-card h2 {
  margin: 0;
}

.brand-copy-wrap h1 {
  font-size: 22px;
  line-height: 1.12;
}

.brand-copy {
  margin: 10px 0 0;
  color: var(--text-muted);
  line-height: 1.65;
}

.section-kicker,
.eyebrow,
.panel-kicker {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.sidebar-nav {
  display: grid;
  gap: 10px;
}

.sidebar-link {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 18px;
  color: var(--text);
  text-align: left;
  background: var(--surface-soft);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease;
}

.sidebar-link:hover {
  transform: translateX(2px);
  border-color: var(--line-strong);
}

.sidebar-link[data-active='true'] {
  border-color: var(--accent-ring);
  background: linear-gradient(180deg, var(--accent-soft), var(--surface-soft));
  box-shadow: 0 0 0 1px var(--accent-ring) inset;
}

.sidebar-link-index {
  flex: none;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  border: 1px solid var(--line);
  color: var(--accent);
  background: var(--surface-elevated);
  font-size: 12px;
  font-weight: 700;
}

.sidebar-link[data-active='true'] .sidebar-link-index {
  border-color: var(--accent-ring);
  background: var(--accent-soft);
}

.sidebar-link-copy {
  display: grid;
  gap: 4px;
}

.sidebar-link-copy small,
.sidebar-note,
.metric-tile span,
.metric-tile small,
.status-card p,
.topbar-chip,
 .topbar-note,
.hero-stat span,
.hero-stat small,
.hero-text,
.queue-overview-card span,
.queue-line,
.queue-raw,
.queue-meta,
.queue-state,
.directory-chip span,
.panel-pill,
.summary-banner p,
.summary-card span,
.result-item p,
.empty-card p,
.brand-copy {
  color: var(--text-muted);
}

.quick-card {
  display: grid;
  gap: 12px;
}

.quick-action-grid {
  display: grid;
  gap: 10px;
}

.quick-action-button,
.mini-button {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface-soft);
  color: var(--text);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    opacity 160ms ease;
}

.quick-action-button {
  width: 100%;
  padding: 12px 14px;
  text-align: left;
}

.mini-button {
  padding: 10px 14px;
}

.quick-action-button:hover:not(:disabled),
.mini-button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--line-strong);
}

.quick-action-button:disabled,
.mini-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.sidebar-link-copy strong {
  font-size: 14px;
  font-weight: 600;
}

.segmented-control {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.theme-option {
  display: grid;
  gap: 4px;
  padding: 12px 10px;
  border: 1px solid var(--line);
  border-radius: 18px;
  color: var(--text);
  background: var(--surface-soft);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    box-shadow 160ms ease;
}

.theme-option:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
}

.theme-option[data-active='true'] {
  border-color: var(--accent-ring);
  background: linear-gradient(180deg, var(--accent-soft), var(--surface-soft));
  box-shadow: 0 0 0 1px var(--accent-ring) inset;
}

.theme-option span {
  font-weight: 600;
}

.theme-option small {
  font-size: 12px;
  line-height: 1.35;
}

.sidebar-note {
  margin: 0;
  font-size: 13px;
}

.metrics-card {
  display: grid;
  gap: 12px;
}

.metric-tile {
  padding: 16px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.metric-tile strong {
  display: block;
  margin-top: 10px;
  font-size: 28px;
  line-height: 1;
}

.status-card {
  display: grid;
  gap: 14px;
}

.status-card[data-tone='info'] {
  border-color: var(--accent-ring);
}

.status-card[data-tone='success'] {
  border-color: var(--good-ring);
}

.status-card[data-tone='warning'] {
  border-color: var(--warn-ring);
}

.status-card[data-tone='danger'] {
  border-color: var(--danger-ring);
}

.status-card h2 {
  font-size: 24px;
  line-height: 1.12;
}

.status-copy {
  margin: 0;
  line-height: 1.7;
}

.status-footer,
.topbar-rail,
.directory-chip,
.action-row,
.button-group,
.queue-topline,
.queue-meta {
  display: flex;
  align-items: center;
}

.status-footer,
.topbar-rail,
.button-group,
.queue-meta {
  gap: 12px;
}

.status-footer,
.topbar-rail,
.queue-meta {
  justify-content: space-between;
}

.topbar-rail {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.status-footer {
  flex-wrap: wrap;
}

.status-pill,
.topbar-chip,
.line-badge {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.status-pill[data-tone='info'],
.topbar-chip[data-tone='info'] {
  color: var(--accent);
  border-color: var(--accent-ring);
}

.status-pill[data-tone='success'],
.topbar-chip[data-tone='success'] {
  color: var(--good);
  border-color: var(--good-ring);
}

.status-pill[data-tone='warning'],
.topbar-chip[data-tone='warning'] {
  color: var(--warn);
  border-color: var(--warn-ring);
}

.status-pill[data-tone='danger'],
.topbar-chip[data-tone='danger'] {
  color: var(--danger);
  border-color: var(--danger-ring);
}

.workspace {
  display: grid;
  gap: 24px;
  min-width: 0;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
}

.topbar-stack {
  display: grid;
  gap: 10px;
  justify-items: end;
}

.topbar-note {
  margin: 0;
  max-width: 440px;
  text-align: right;
  line-height: 1.5;
}

.window-statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  padding: 14px 18px;
  flex-wrap: wrap;
}

.topbar h2 {
  font-size: clamp(22px, 2vw, 28px);
  line-height: 1.08;
}

.hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.82fr);
  gap: 24px;
  padding: 30px;
}

.hero-copy h1 {
  font-size: clamp(36px, 4.2vw, 64px);
  line-height: 1.04;
  letter-spacing: -0.03em;
}

.hero-text {
  max-width: 720px;
  margin: 18px 0 0;
  font-size: 17px;
  line-height: 1.8;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 20px;
}

.hero-tag {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--accent);
  background: var(--accent-soft);
}

.hero-stats,
.summary-grid {
  display: grid;
  gap: 14px;
}

.hero-stats {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.hero-stat,
.summary-card {
  padding: 18px;
  border-radius: 22px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.hero-stat strong,
.summary-card strong {
  display: block;
  margin-top: 10px;
  font-size: 28px;
  line-height: 1;
}

.hero-stat-wide {
  grid-column: 1 / -1;
}

.hero-directory {
  font-size: 16px !important;
  line-height: 1.6 !important;
  overflow-wrap: anywhere;
}

.content-grid,
.result-grid {
  display: grid;
  gap: 24px;
}

.content-grid {
  grid-template-columns: minmax(0, 1.06fr) minmax(360px, 0.94fr);
}

.result-grid {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.panel-card {
  padding: 24px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.panel-toolbar,
.panel-pills,
.panel-tools {
  display: flex;
  align-items: center;
}

.panel-toolbar {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.panel-pills,
.panel-tools {
  gap: 10px;
  flex-wrap: wrap;
}

.panel-pill {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.panel-pill[data-tone='accent'] {
  color: var(--accent);
  border-color: var(--accent-ring);
}

.panel-pill[data-tone='success'] {
  color: var(--good);
  border-color: var(--good-ring);
}

.panel-pill[data-tone='warning'] {
  color: var(--warn);
  border-color: var(--warn-ring);
}

.line-badge {
  color: var(--accent);
  background: var(--accent-soft);
}

.input-area {
  width: 100%;
  min-height: 340px;
  resize: vertical;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 24px;
  color: var(--text);
  background: var(--surface-elevated);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.input-area::placeholder {
  color: var(--text-muted-soft);
}

.action-row {
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  flex-wrap: wrap;
}

.directory-chip {
  flex: 1 1 280px;
  gap: 14px;
  min-height: 56px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--surface-soft);
}

.directory-chip strong {
  overflow-wrap: anywhere;
}

.button-group {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.button {
  border: 0;
  border-radius: 14px;
  padding: 13px 18px;
  cursor: pointer;
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    opacity 160ms ease,
    background 160ms ease;
}

.button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.button.ghost {
  color: var(--text);
  border: 1px solid var(--line-strong);
  background: var(--surface-soft);
}

.button.solid {
  color: var(--accent-text);
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent), var(--accent-strong));
  box-shadow: 0 16px 32px var(--accent-shadow);
}

.queue-overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.queue-overview-card {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.queue-overview-card strong {
  display: block;
  margin-top: 8px;
  font-size: 22px;
  line-height: 1;
}

.queue-overview-card[data-tone='info'] {
  border-color: var(--accent-ring);
}

.queue-overview-card[data-tone='success'] {
  border-color: var(--good-ring);
}

.queue-overview-card[data-tone='danger'] {
  border-color: var(--danger-ring);
}

.queue-list,
.result-list {
  display: grid;
  gap: 12px;
}

.queue-item,
.result-item,
.empty-card {
  padding: 16px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.queue-item {
  transition:
    border-color 160ms ease,
    transform 160ms ease,
    box-shadow 160ms ease;
}

.queue-item[data-active='true'] {
  border-color: var(--accent-ring);
  box-shadow: 0 0 0 1px var(--accent-ring) inset;
}

.queue-item[data-status='success'] {
  border-color: var(--good-ring);
}

.queue-item[data-status='failed'],
.queue-item[data-status='invalid'] {
  border-color: var(--danger-ring);
}

.queue-topline {
  justify-content: space-between;
  gap: 12px;
}

.queue-line,
.queue-raw {
  margin: 0;
}

.queue-line {
  margin-bottom: 6px;
}

.queue-raw {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.queue-state {
  flex: none;
  padding: 8px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  text-transform: none;
  font-size: 12px;
  letter-spacing: 0.04em;
  background: var(--surface-elevated);
}

.queue-item[data-status='success'] .queue-state {
  color: var(--good);
}

.queue-item[data-status='failed'] .queue-state,
.queue-item[data-status='invalid'] .queue-state {
  color: var(--danger);
}

.progress-track {
  position: relative;
  height: 10px;
  overflow: hidden;
  margin-top: 14px;
  border-radius: 999px;
  background: rgba(95, 107, 122, 0.18);
}

.progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--accent-strong));
  transition: width 220ms ease;
}

.queue-meta {
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-muted);
}

.log-console {
  min-height: 380px;
  max-height: 560px;
  overflow: auto;
  padding: 18px;
  border-radius: 22px;
  border: 1px solid var(--line);
  background:
    linear-gradient(180deg, var(--surface-strong), transparent),
    var(--surface-elevated);
}

.log-console p {
  margin: 0 0 10px;
  color: var(--text);
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.summary-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 16px;
}

.summary-banner {
  margin-bottom: 16px;
  padding: 16px 18px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
}

.summary-banner[data-tone='info'] {
  border-color: var(--accent-ring);
}

.summary-banner[data-tone='success'] {
  border-color: var(--good-ring);
}

.summary-banner[data-tone='warning'] {
  border-color: var(--warn-ring);
}

.summary-banner[data-tone='danger'] {
  border-color: var(--danger-ring);
}

.summary-banner strong {
  display: block;
  margin-top: 6px;
  font-size: 20px;
  line-height: 1.3;
}

.summary-banner-label,
.result-section-title {
  display: block;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.summary-banner p {
  margin: 10px 0 0;
  line-height: 1.65;
}

.result-section-title {
  margin: 0 0 10px;
}

.summary-card {
  display: grid;
  gap: 8px;
}

.result-list {
  margin-top: 16px;
}

.result-item.success {
  border-color: var(--good-ring);
}

.result-item.failure {
  border-color: var(--danger-ring);
}

.result-item p,
.empty-card p {
  margin: 10px 0 0;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.empty-card {
  display: grid;
  place-items: start;
  min-height: 180px;
  border-style: dashed;
}

.empty-card.compact {
  min-height: auto;
  margin-top: 16px;
}

@media (max-width: 1220px) {
  .commandbar {
    flex-direction: column;
    align-items: stretch;
  }

  .commandbar-info {
    min-width: 0;
    justify-items: start;
  }

  .commandbar-chip-row {
    justify-content: flex-start;
  }

  .commandbar-note,
  .commandbar-path {
    text-align: left;
  }

  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: relative;
    top: auto;
  }

  .content-grid,
  .result-grid,
  .hero-card {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .window-shell {
    width: min(100% - 10px, 1760px);
    margin: 5px auto;
    padding: 6px;
    border-radius: 24px;
  }

  .window-titlebar,
  .commandbar,
  .window-statusbar,
  .sidebar,
  .topbar,
  .hero-card,
  .panel-card {
    padding: 18px;
    border-radius: 24px;
  }

  .window-titlebar,
  .commandbar,
  .window-statusbar {
    gap: 14px;
  }

  .window-titlebar,
  .window-statusbar {
    flex-direction: column;
    align-items: stretch;
  }

  .window-caption,
  .window-caption-spacer {
    min-height: auto;
  }

  .window-controls {
    justify-content: flex-end;
  }

  .segmented-control,
  .hero-stats,
  .queue-overview-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .topbar,
  .topbar-stack,
  .panel-toolbar,
  .action-row,
  .status-footer,
  .queue-topline,
  .queue-meta {
    flex-direction: column;
    align-items: stretch;
  }

  .topbar-note {
    max-width: none;
    text-align: left;
  }

  .commandbar-note,
  .commandbar-path {
    max-width: none;
  }

  .topbar-rail {
    justify-content: flex-start;
  }

  .commandbar-actions,
  .commandbar-chip-row,
  .button-group,
  .topbar-rail {
    width: 100%;
  }

  .window-statusbar span,
  .commandbar-button,
  .panel-tools,
  .button,
  .theme-option {
    width: 100%;
  }

  .hero-copy h1 {
    font-size: 34px;
  }

  .input-area,
  .log-console {
    min-height: 280px;
  }
}

@keyframes rise-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sidebar {
  animation: rise-in 420ms ease both;
}

.topbar {
  animation: rise-in 420ms ease both;
  animation-delay: 40ms;
}

.hero-card {
  animation: rise-in 420ms ease both;
  animation-delay: 80ms;
}

.content-grid {
  animation: rise-in 420ms ease both;
  animation-delay: 120ms;
}

.result-grid {
  animation: rise-in 420ms ease both;
  animation-delay: 160ms;
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }

  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}
</style>
