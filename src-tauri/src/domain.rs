use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadInput {
  pub line_number: usize,
  pub value: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadSummary {
  pub total: usize,
  pub success_count: usize,
  pub failure_count: usize,
  pub succeeded: Vec<DownloadOutcome>,
  pub failed: Vec<DownloadFailure>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadOutcome {
  pub line_number: usize,
  pub extension_id: String,
  pub file_path: String,
  pub bytes_written: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadFailure {
  pub line_number: usize,
  pub input: String,
  pub reason: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum DownloadEvent {
  BatchStarted {
    total: usize,
  },
  #[serde(rename_all = "camelCase")]
  ItemStarted {
    index: usize,
    total: usize,
    line_number: usize,
    extension_id: String,
    file_name: String,
  },
  #[serde(rename_all = "camelCase")]
  ItemProgress {
    index: usize,
    total: usize,
    line_number: usize,
    downloaded_bytes: u64,
    total_bytes: Option<u64>,
  },
  #[serde(rename_all = "camelCase")]
  ItemSucceeded {
    index: usize,
    total: usize,
    line_number: usize,
    extension_id: String,
    file_path: String,
    bytes_written: u64,
  },
  #[serde(rename_all = "camelCase")]
  ItemFailed {
    index: usize,
    total: usize,
    line_number: usize,
    input: String,
    reason: String,
  },
}

#[derive(Debug)]
pub struct DownloadTarget {
  pub line_number: usize,
  pub extension_id: String,
}
