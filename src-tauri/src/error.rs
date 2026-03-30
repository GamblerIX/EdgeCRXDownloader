use std::{io, path::PathBuf};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum DownloadError {
  #[error("输入不能为空")]
  EmptyInput,
  #[error("无效的扩展 ID 或 Edge 商店 URL：{0}")]
  InvalidInput(String),
  #[error("保存目录无效：{0}")]
  InvalidSaveDirectory(String),
  #[error("无法创建保存目录：{0}")]
  CreateDirectory(String),
  #[error("网络请求失败：{0}")]
  Network(String),
  #[error("HTTP 响应异常：{0}")]
  HttpStatus(u16),
  #[error("文件写入失败：{0}")]
  FileWrite(String),
  #[error("无法重命名临时文件到目标文件：{0}")]
  Rename(String),
}

impl From<io::Error> for DownloadError {
  fn from(error: io::Error) -> Self {
    Self::FileWrite(error.to_string())
  }
}

impl DownloadError {
  pub fn create_directory(path: &PathBuf, error: io::Error) -> Self {
    Self::CreateDirectory(format!("{} ({})", path.display(), error))
  }
}
