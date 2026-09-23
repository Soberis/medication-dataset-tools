# medication-dataset-tools

首阶段工具：从有使用权的 B 站视频 URL 下载不超过 720p 的副本，保存来源信息，并按采样帧中的手部检测比例生成候选状态。`ACCEPTED` 仅代表手部占比达标；第一视角、配药相关性和训练使用权仍须人工核验。工具不会自动向 Platform 入库。

## 使用

需要 Python 3.11 或 3.12、`ffmpeg`。安装依赖：`python -m pip install -r requirements.txt`。复制 `urls.example.csv` 为 `urls.csv`，逐条填写真实 URL 和授权/许可依据。空白依据会被拒绝；请勿绕过登录、付费或访问控制。

```powershell
python dataset.py download --urls urls.csv
python dataset.py screen
```

输出位于 `raw/<video_id>/` 和 `metadata/manifest.json`。筛选默认每秒采 2 帧，`hand_ratio >= 0.60` 为 `ACCEPTED`，`0.20–0.60` 为 `REVIEW`，其余为 `REJECTED`。原视频始终留在 `raw/`，筛选状态可重算。`raw/`、`metadata/` 和私人 URL 清单不进入 Git。
