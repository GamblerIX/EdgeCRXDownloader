use std::{
  path::{Path, PathBuf},
  sync::LazyLock,
  time::Duration,
};

use regex::Regex;
use reqwest::Client;
use tauri::ipc::Channel;
use tokio::{fs, io::AsyncWriteExt};

use crate::{
  domain::{
    DownloadEvent, DownloadFailure, DownloadInput, DownloadOutcome, DownloadSummary,
    DownloadTarget,
  },
  error::DownloadError,
};

const EDGE_USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0";
const CRX_MAGIC: &[u8; 4] = b"Cr24";
const DOWNLOAD_URL_TEMPLATE: &str = "https://edge.microsoft.com/extensionwebstorebase/v1/crx?response=redirect&prod=chromiumcrx&prodchannel=&x=id%3D{ID}%26installsource%3Dondemand%26uc";

#[tauri::command]
pub async fn download_extensions(
  inputs: Vec<DownloadInput>,
  save_dir: String,
  progress: Channel<DownloadEvent>,
) -> Result<DownloadSummary, String> {
  download_extensions_inner(inputs, save_dir, progress)
    .await
    .map_err(|error| error.to_string())
}

async fn download_extensions_inner(
  inputs: Vec<DownloadInput>,
  save_dir: String,
  progress: Channel<DownloadEvent>,
) -> Result<DownloadSummary, DownloadError> {
  if inputs.is_empty() {
    return Err(DownloadError::EmptyInput);
  }

  let save_dir = PathBuf::from(save_dir.trim());
  if save_dir.as_os_str().is_empty() {
    return Err(DownloadError::InvalidSaveDirectory("路径为空".to_string()));
  }

  fs::create_dir_all(&save_dir)
    .await
    .map_err(|error| DownloadError::create_directory(&save_dir, error))?;

  let client = &*HTTP_CLIENT;
  let total = inputs.len();
  let _ = progress.send(DownloadEvent::BatchStarted { total });

  let mut succeeded = Vec::new();
  let mut failed = Vec::new();

  for (index, input) in inputs.into_iter().enumerate() {
    let item_index = index + 1;
    match resolve_target(&input) {
      Ok(target) => match download_one(&client, &save_dir, &target, item_index, total, &progress)
        .await
      {
        Ok(outcome) => succeeded.push(outcome),
        Err(error) => {
          let reason = error.to_string();
          failed.push(DownloadFailure {
            line_number: input.line_number,
            input: input.value.clone(),
            reason: reason.clone(),
          });
          let _ = progress.send(DownloadEvent::ItemFailed {
            index: item_index,
            total,
            line_number: input.line_number,
            input: input.value,
            reason,
          });
        }
      },
      Err(error) => {
        let reason = error.to_string();
        failed.push(DownloadFailure {
          line_number: input.line_number,
          input: input.value.clone(),
          reason: reason.clone(),
        });
        let _ = progress.send(DownloadEvent::ItemFailed {
          index: item_index,
          total,
          line_number: input.line_number,
          input: input.value,
          reason,
        });
      }
    }
  }

  let success_count = succeeded.len();
  let failure_count = failed.len();

  Ok(DownloadSummary {
    total,
    success_count,
    failure_count,
    succeeded,
    failed,
  })
}

static HTTP_CLIENT: LazyLock<Client> = LazyLock::new(|| {
  Client::builder()
    .user_agent(EDGE_USER_AGENT)
    .timeout(Duration::from_secs(600))
    .build()
    .expect("failed to build HTTP client")
});

fn resolve_target(input: &DownloadInput) -> Result<DownloadTarget, DownloadError> {
static DIRECT_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z]{32}$").unwrap());
static URL_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"microsoftedge\.microsoft\.com/addons/detail/[^/]+/([a-z]{32})").unwrap());

  let normalized = input.value.trim().to_lowercase();

  if normalized.is_empty() {
    return Err(DownloadError::EmptyInput);
  }

  if DIRECT_PATTERN.is_match(&normalized) {
    return Ok(DownloadTarget {
      line_number: input.line_number,
      extension_id: normalized,
    });
  }

  if let Some(captures) = URL_PATTERN.captures(&normalized) {
    let extension_id = captures
      .get(1)
      .map(|match_| match_.as_str().to_string())
      .unwrap_or_default();

    if !extension_id.is_empty() {
      return Ok(DownloadTarget {
        line_number: input.line_number,
        extension_id,
      });
    }
  }

  Err(DownloadError::InvalidInput(
    "请填写 32 位扩展 ID，或 Edge 商店详情页 URL".to_string(),
  ))
}

async fn download_one(
  client: &Client,
  save_dir: &Path,
  target: &DownloadTarget,
  index: usize,
  total: usize,
  progress: &Channel<DownloadEvent>,
) -> Result<DownloadOutcome, DownloadError> {
  let file_name = format!("{}.crx", target.extension_id);
  let output_path = save_dir.join(&file_name);
  let temp_path = save_dir.join(format!("{}.partial", file_name));
  let download_url = DOWNLOAD_URL_TEMPLATE.replace("{ID}", &target.extension_id);

  let _ = progress.send(DownloadEvent::ItemStarted {
    index,
    total,
    line_number: target.line_number,
    extension_id: target.extension_id.clone(),
    file_name: file_name.clone(),
  });

  let mut response = client
    .get(download_url)
    .send()
    .await
    .map_err(|error| DownloadError::Network(error.to_string()))?;

  if !response.status().is_success() {
    return Err(DownloadError::HttpStatus(response.status().as_u16()));
  }

  if temp_path.exists() {
    let _ = fs::remove_file(&temp_path).await;
  }

  let total_bytes = response.content_length();
  let mut downloaded_bytes = 0_u64;
  let mut file = fs::File::create(&temp_path)
    .await
    .map_err(|error| DownloadError::FileWrite(format!("{} ({})", temp_path.display(), error)))?;

  let download_result: Result<(), DownloadError> = async {
    while let Some(chunk) = response
      .chunk()
      .await
      .map_err(|error| DownloadError::Network(error.to_string()))?
    {
      file.write_all(&chunk)
        .await
        .map_err(|error| DownloadError::FileWrite(format!("{} ({})", temp_path.display(), error)))?;

      downloaded_bytes += chunk.len() as u64;
      let _ = progress.send(DownloadEvent::ItemProgress {
        index,
        total,
        line_number: target.line_number,
        downloaded_bytes,
        total_bytes,
      });
    }

    file.flush()
      .await
      .map_err(|error| DownloadError::FileWrite(format!("{} ({})", temp_path.display(), error)))?;

    Ok(())
  }
  .await;

  drop(file);

  if let Err(error) = download_result {
    let _ = fs::remove_file(&temp_path).await;
    return Err(error);
  }

  // Validate CRX magic bytes to detect error pages served with 2xx status.
  let mut magic_buf = [0u8; 4];
  {
    let mut f = fs::File::open(&temp_path)
      .await
      .map_err(|error| DownloadError::FileWrite(format!("{} ({})", temp_path.display(), error)))?;
    use tokio::io::AsyncReadExt;
    f.read_exact(&mut magic_buf)
      .await
      .map_err(|_| DownloadError::FileWrite("下载的文件过小，可能不是有效的 CRX 文件".to_string()))?;
  }

  if &magic_buf != CRX_MAGIC {
    let _ = fs::remove_file(&temp_path).await;
    return Err(DownloadError::FileWrite("文件头不匹配 CRX 格式，服务器可能返回了错误页面".to_string()));
  }

  if output_path.exists() {
    fs::remove_file(&output_path)
      .await
      .map_err(|error| DownloadError::Rename(format!("{} ({})", output_path.display(), error)))?;
  }

  fs::rename(&temp_path, &output_path)
    .await
    .map_err(|error| {
      DownloadError::Rename(format!(
        "{} -> {} ({})",
        temp_path.display(),
        output_path.display(),
        error
      ))
    })?;

  let _ = progress.send(DownloadEvent::ItemSucceeded {
    index,
    total,
    line_number: target.line_number,
    extension_id: target.extension_id.clone(),
    file_path: output_path.display().to_string(),
    bytes_written: downloaded_bytes,
  });

  Ok(DownloadOutcome {
    line_number: target.line_number,
    extension_id: target.extension_id.clone(),
    file_path: output_path.display().to_string(),
    bytes_written: downloaded_bytes,
  })
}
