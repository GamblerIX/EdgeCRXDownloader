export interface DownloadInputPayload {
  lineNumber: number
  value: string
}

const DIRECT_ID_PATTERN = /^[a-z]{32}$/
const STORE_URL_PATTERN =
  /microsoftedge\.microsoft\.com\/addons\/detail\/[^/]+\/([a-z]{32})/i

export function extractExtensionId(value: string): string | null {
  const normalized = value.trim().toLowerCase()

  if (!normalized) {
    return null
  }

  if (DIRECT_ID_PATTERN.test(normalized)) {
    return normalized
  }

  const match = normalized.match(STORE_URL_PATTERN)
  return match?.[1] ?? null
}

export function parseExtensionInputs(raw: string): DownloadInputPayload[] {
  return raw
    .split(/\r?\n/)
    .map((value, index) => ({
      lineNumber: index + 1,
      value: value.trim()
    }))
    .filter((item) => item.value.length > 0)
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B'
  }

  const units = ['B', 'KB', 'MB', 'GB']
  let unitIndex = 0
  let size = value

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }

  const digits = size >= 100 || unitIndex === 0 ? 0 : 1
  return `${size.toFixed(digits)} ${units[unitIndex]}`
}

export function formatPercent(downloaded: number, total?: number | null): string {
  if (!total || total <= 0) {
    return '...'
  }

  const percent = Math.max(0, Math.min(100, (downloaded / total) * 100))
  return `${percent.toFixed(percent >= 10 ? 0 : 1)}%`
}
