<script setup lang="ts">
import { Channel, invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
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

let mediaQuery: MediaQueryList | null = null

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
  return !isRunning.value && saveDir.value.trim().length > 0 && queueStats.value.total > 0
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
})

onBeforeUnmount(() => {
  if (mediaQuery) {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  }
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

function setThemeMode(mode: ThemeMode) {
  themeMode.value = mode
}

function scrollToSection(sectionId: string) {
  if (typeof document === 'undefined') {
    return
  }

  const target = document.getElementById(sectionId)
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
      break
    }

    case 'itemProgress': {
      const item = findQueueItem(event.lineNumber)
      if (item) {
        item.status = 'running'
        item.downloadedBytes = event.downloadedBytes
        item.totalBytes = event.totalBytes ?? null
      }
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
      break
    }

    case 'itemFailed': {
      const item = findQueueItem(event.lineNumber)
      if (item) {
        item.status =
          item.extensionId || !event.reason.includes('32 位扩展 ID') ? 'failed' : 'invalid'
        item.error = event.reason
      }
      appendLog(`第 ${event.lineNumber} 行失败：${event.reason}`)
      break
    }
  }
}

async function chooseDirectory() {
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
  } catch (error) {
    const message = getUserFacingError(error)
    setStatus('执行异常', message, 'danger')
    appendLog(message)
  } finally {
    isRunning.value = false
    activeLine.value = null
  }
}
</script>

<template>
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

      <section class="sidebar-card metrics-card">
        <article v-for="metric in sidebarMetrics" :key="metric.label" class="metric-tile">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.hint }}</small>
        </article>
      </section>

      <section class="sidebar-card status-card" :data-tone="statusTone">
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
        <div class="topbar-rail">
          <span class="topbar-chip">{{ themeSummary }}</span>
          <span class="topbar-chip" :data-tone="statusTone">
            {{ isRunning ? '执行中' : '已就绪' }}
          </span>
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
              <button class="focus-ring button ghost" type="button" @click="chooseDirectory">
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

              <div class="progress-track">
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

          <div ref="logPanel" class="log-console mono">
            <p v-for="entry in logs" :key="entry">{{ entry }}</p>
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
</template>

<style scoped>
.app-shell {
  width: min(1680px, calc(100% - 28px));
  margin: 0 auto;
  padding: 22px 0 42px;
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
.hero-stat span,
.hero-stat small,
.hero-text,
.queue-line,
.queue-raw,
.queue-meta,
.queue-state,
.directory-chip span,
.summary-card span,
.result-item p,
.empty-card p,
.brand-copy {
  color: var(--text-muted);
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
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
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
  .app-shell {
    width: min(100% - 18px, 1680px);
    padding-top: 16px;
    padding-bottom: 28px;
  }

  .sidebar,
  .topbar,
  .hero-card,
  .panel-card {
    padding: 18px;
    border-radius: 24px;
  }

  .segmented-control,
  .hero-stats,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .topbar,
  .action-row,
  .status-footer,
  .queue-topline,
  .queue-meta {
    flex-direction: column;
    align-items: stretch;
  }

  .button-group,
  .topbar-rail {
    width: 100%;
  }

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
