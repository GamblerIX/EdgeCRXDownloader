<script setup lang="ts">
import { Channel, invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { computed, nextTick, ref, watch } from 'vue'
import { getUserFacingError } from '~/utils/error'
import {
  extractExtensionId,
  formatBytes,
  formatPercent,
  parseExtensionInputs
} from '~/utils/extension'

type QueueStatus = 'waiting' | 'running' | 'success' | 'failed' | 'invalid'
type StatusTone = 'info' | 'success' | 'warning' | 'danger'

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

const sampleInput = [
  'iikmkjmpaadaobahmlepeloendndfphd',
  'https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN'
].join('\n')

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

useHead({
  title: 'Edge CRX Downloader'
})

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

const queueStats = computed(() => {
  const total = queue.value.length
  const valid = queue.value.filter((item) => item.extensionId).length
  const invalid = queue.value.filter((item) => item.status === 'invalid').length
  const running = queue.value.filter((item) => item.status === 'running').length
  const success = queue.value.filter((item) => item.status === 'success').length
  const failed = queue.value.filter(
    (item) => item.status === 'failed' || item.status === 'invalid'
  ).length

  return { total, valid, invalid, running, success, failed }
})

const canStart = computed(() => {
  return !isRunning.value && saveDir.value.trim().length > 0 && queueStats.value.total > 0
})

const totalWritten = computed(() => {
  if (summary.value) {
    return summary.value.succeeded.reduce((total, item) => total + item.bytesWritten, 0)
  }

  return queue.value.reduce((total, item) => total + item.downloadedBytes, 0)
})

const successRate = computed(() => {
  const total = summary.value?.total ?? queueStats.value.total
  const success = summary.value?.successCount ?? queueStats.value.success

  if (total <= 0) {
    return '0%'
  }

  return `${Math.round((success / total) * 100)}%`
})

function buildQueueEntries(source: string): QueueItem[] {
  return parseExtensionInputs(source).map((item) => ({
    lineNumber: item.lineNumber,
    raw: item.value,
    extensionId: extractExtensionId(item.value),
    status: extractExtensionId(item.value) ? 'waiting' : 'invalid',
    downloadedBytes: 0,
    totalBytes: null,
    filePath: null,
    error: null
  }))
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
  return queue.value.find((item) => item.lineNumber === lineNumber) ?? null
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
  progress.onmessage = (message) => {
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
    <section class="status-banner" :data-tone="statusTone">
      <div>
        <p class="banner-label">Desktop Pipeline</p>
        <h2>{{ statusTitle }}</h2>
      </div>
      <p>{{ statusMessage }}</p>
    </section>

    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">Nuxt + Tauri v2</p>
        <h1>批量抓取 Microsoft Edge 扩展 CRX，进度、日志和结果都留在桌面端。</h1>
        <p class="hero-text">
          输入 32 位扩展 ID 或 Edge 商店详情页链接，选择一个本地目录，桌面端会用 Rust
          下载引擎逐项抓取并反馈实时进度。
        </p>
      </div>

      <div class="metric-grid">
        <article class="metric-card">
          <span>队列总数</span>
          <strong>{{ queueStats.total }}</strong>
          <small>{{ queueStats.valid }} 项可执行，{{ queueStats.invalid }} 项待校验</small>
        </article>
        <article class="metric-card">
          <span>成功率</span>
          <strong>{{ successRate }}</strong>
          <small>{{ queueStats.success }} 成功 / {{ queueStats.failed }} 失败</small>
        </article>
        <article class="metric-card">
          <span>已写入</span>
          <strong>{{ formatBytes(totalWritten) }}</strong>
          <small>{{ isRunning ? '任务仍在执行' : '等待下一轮批量下载' }}</small>
        </article>
      </div>
    </section>

    <section class="workspace-grid">
      <article class="panel-card panel-input">
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

      <article class="panel-card panel-queue">
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
              <span class="queue-state">{{ item.status }}</span>
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

    <section class="result-grid">
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

        <div v-if="summary?.succeeded.length" class="result-list">
          <article
            v-for="item in summary.succeeded"
            :key="`${item.lineNumber}-${item.extensionId}`"
            class="result-item success"
          >
            <h4>{{ item.extensionId }}</h4>
            <p class="mono">{{ item.filePath }}</p>
          </article>
        </div>

        <div v-if="summary?.failed.length" class="result-list">
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
  </main>
</template>

<style scoped>
.status-banner {
  position: sticky;
  top: 18px;
  z-index: 20;
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 22px;
  margin-bottom: 22px;
  border: 1px solid var(--line);
  border-radius: 22px;
  backdrop-filter: blur(24px);
  box-shadow: var(--shadow);
  background: rgba(18, 16, 12, 0.84);
}

.status-banner[data-tone="success"] {
  border-color: rgba(166, 217, 126, 0.35);
}

.status-banner[data-tone="warning"] {
  border-color: rgba(242, 190, 92, 0.35);
}

.status-banner[data-tone="danger"] {
  border-color: rgba(255, 125, 125, 0.35);
}

.banner-label,
.eyebrow,
.panel-kicker {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.status-banner h2,
.panel-head h3,
.empty-card h4,
.queue-item h4,
.result-item h4 {
  margin: 0;
}

.status-banner p:last-child {
  margin: 0;
  max-width: 520px;
  color: var(--text-muted);
}

.hero-card,
.panel-card {
  border: 1px solid var(--line);
  border-radius: 28px;
  background: linear-gradient(180deg, rgba(35, 32, 26, 0.9), rgba(20, 18, 14, 0.9));
  box-shadow: var(--shadow);
  backdrop-filter: blur(20px);
}

.hero-card {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 26px;
  padding: 34px;
  margin-bottom: 24px;
}

.hero-copy h1 {
  margin: 0;
  max-width: 760px;
  font-size: clamp(34px, 4vw, 60px);
  line-height: 1.02;
}

.hero-text {
  max-width: 700px;
  margin: 18px 0 0;
  font-size: 17px;
  line-height: 1.7;
  color: var(--text-muted);
}

.metric-grid,
.summary-grid {
  display: grid;
  gap: 14px;
}

.metric-card,
.summary-card {
  padding: 18px 20px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.03);
}

.metric-card span,
.summary-card span {
  display: block;
  color: var(--text-muted);
}

.metric-card strong,
.summary-card strong {
  display: block;
  margin-top: 10px;
  font-size: 30px;
}

.metric-card small {
  display: block;
  margin-top: 8px;
  color: var(--text-muted);
}

.workspace-grid,
.result-grid {
  display: grid;
  gap: 24px;
  margin-top: 24px;
}

.workspace-grid {
  grid-template-columns: 1.08fr 0.92fr;
}

.result-grid {
  grid-template-columns: 1fr 1fr;
}

.panel-card {
  padding: 26px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.line-badge {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--info);
  background: rgba(140, 200, 255, 0.08);
}

.input-area {
  width: 100%;
  min-height: 320px;
  resize: vertical;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 22px;
  color: var(--text);
  background: rgba(8, 8, 8, 0.26);
}

.input-area::placeholder {
  color: rgba(247, 240, 221, 0.32);
}

.action-row,
.button-group,
.directory-chip,
.queue-topline,
.queue-meta {
  display: flex;
  align-items: center;
}

.action-row {
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
}

.button-group {
  gap: 12px;
}

.directory-chip {
  gap: 14px;
  flex-wrap: wrap;
  min-height: 56px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.03);
}

.directory-chip span {
  color: var(--text-muted);
}

.button {
  border: 0;
  border-radius: 16px;
  padding: 13px 18px;
  cursor: pointer;
  transition:
    transform 180ms ease,
    opacity 180ms ease,
    background 180ms ease;
}

.button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.button.ghost {
  color: var(--text);
  border: 1px solid var(--line-strong);
  background: rgba(255, 255, 255, 0.04);
}

.button.solid {
  color: #18130c;
  font-weight: 700;
  background: linear-gradient(135deg, var(--amber), var(--amber-strong));
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
  background: rgba(255, 255, 255, 0.03);
}

.queue-item[data-active="true"] {
  border-color: rgba(242, 190, 92, 0.4);
}

.queue-item[data-status="success"] {
  border-color: rgba(166, 217, 126, 0.34);
}

.queue-item[data-status="failed"],
.queue-item[data-status="invalid"] {
  border-color: rgba(255, 125, 125, 0.28);
}

.queue-topline {
  justify-content: space-between;
  gap: 12px;
}

.queue-line,
.queue-raw {
  margin: 0;
  color: var(--text-muted);
}

.queue-line {
  margin-bottom: 6px;
}

.queue-raw {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.queue-state {
  padding: 8px 10px;
  border-radius: 999px;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.05);
}

.progress-track {
  position: relative;
  height: 9px;
  overflow: hidden;
  margin-top: 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}

.progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--olive), var(--amber));
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
  max-height: 520px;
  overflow: auto;
  padding: 18px;
  border-radius: 22px;
  border: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(0, 0, 0, 0.24), rgba(0, 0, 0, 0.4)),
    radial-gradient(circle at top left, rgba(140, 161, 107, 0.12), transparent 30%);
}

.log-console p {
  margin: 0 0 10px;
  color: rgba(247, 240, 221, 0.84);
  line-height: 1.6;
}

.result-list {
  margin-top: 16px;
}

.result-item.success {
  border-color: rgba(166, 217, 126, 0.3);
}

.result-item.failure {
  border-color: rgba(255, 125, 125, 0.26);
}

.result-item p,
.empty-card p {
  margin: 10px 0 0;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}

.empty-card {
  display: grid;
  place-items: start;
  min-height: 180px;
}

.empty-card.compact {
  min-height: auto;
  margin-top: 16px;
}

@media (max-width: 1080px) {
  .hero-card,
  .workspace-grid,
  .result-grid,
  .status-banner,
  .action-row {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }

  .button-group {
    width: 100%;
  }

  .button {
    flex: 1;
  }
}

@media (max-width: 720px) {
  .app-shell {
    width: min(100% - 20px, 1320px);
    padding-top: 18px;
  }

  .hero-card,
  .panel-card,
  .status-banner {
    border-radius: 22px;
    padding: 20px;
  }

  .hero-copy h1 {
    font-size: 32px;
  }

  .input-area,
  .log-console {
    min-height: 280px;
  }
}
</style>
