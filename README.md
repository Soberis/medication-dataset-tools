# 第一人称临床配药视频数据集采集与清洗工具集 (medication-dataset-tools)

一套面向医疗具身智能、手术/配药动作识别与临床教学的大规模第一人称（POV）配药视频自动化检索、采集、抽样帧分析、跨平台排重与来源档案管理工具库。

---

## 🌟 核心特性

1. **全平台覆盖**：支持 **抖音 (Douyin)**、**小红书 (XHS)**、**B站 (Bilibili)**、**YouTube (Shorts/Videos)** 多源视频抓取与元数据解析。
2. **第一人称视线与手部特写优先**：内置临床专业关键词词库与精准负向过滤规则，自动剔除科普讲座、非实操播报、游戏 ASMR 及剧情演绎，聚焦双手操作、安瓿瓶徒手折断、西林瓶加药溶解、注射器抽吸排气、静脉穿刺等实操环节。
3. **标准化样本封装规范**：
   - 目录规范：`<platform>_<id> - <视频标题> - <博主姓名>`
   - 完备元数据：包含原画视频（`.mp4`）、原图封面（`cover.jpg`）、结构化信息（`*.info.json`）。
   - 手部动作抽样帧：自动提取操作核心抽帧（`frame_sample.jpg`），方便在文件资源管理器中进行纯视觉快速人工质检。
4. **科学跨平台感知哈希（pHash）去重**：利用 OpenCV + DCT 算法对比视频关键帧，结合标题编辑距离与时长差异，自动识别跨平台搬运、同源重发，支持画质择优合并。
5. **大道至简的单一来源档案**：全量样本统一汇总归档于 `data/临床配药样本来源档案.csv`，严格杜绝冗余表格与混乱文件名。
6. **存储路径隔离**：默认存储于 `D:\下载\第一人称配药实操视频\`，自动兼容原 C 盘历史目录的多目录联合检索与查重。

---

## 📁 科学工程目录划分

```text
medication-dataset-tools/
├── main.py                     # 全功能 CLI 统一命令行入口 (search/download/social/auto-search)
├── download_nurse_pov.py       # 剪贴板实时监听与跨平台快捷下载入口
├── auto_download_youtube.py    # YouTube 配药与护理第一视角全自动搜索下载器
├── pytest.ini                  # 单元测试自动发现配置
├── requirements.txt            # 项目依赖清单
├── README.md                   # 工程设计与使用文档
│
├── config/                     # 检索与过滤词库配置
│   └── keywords.txt            # 关键词与负向排除词库
│
├── data/                       # 数据集档案与凭据存储
│   └── 临床配药样本来源档案.csv # 唯一的创作者与样本统计档案单表
│
├── src/                        # 核心模块
│   ├── downloader.py           # B站批量下载器
│   ├── manifest.py             # 候选列表读写与安全事务
│   ├── search.py               # B站 API 搜索与关键词候选清洗
│   ├── social_downloader.py    # 抖音 / 小红书 / YouTube / B站 统一解析下载引擎
│   └── social_search.py        # 浏览器会话与自动化搜索模块
│
├── tests/                      # 单元测试套件
│   └── test_workflow.py        # 核心工作流自动化测试 (pytest 100% 通过)
│
└── tools/                      # 运维与深度采集工具箱
    ├── generate_creator_table.py # 扫描多目录生成唯一的《临床配药样本来源档案.csv》
    ├── dedup_cross_platform.py # 跨平台去重与视频感知哈希比对工具
    ├── harvest_xhs_creators.py # 小红书指定临床护士主页自动化批量采集
    ├── download_single_xhs.py  # 小红书单条视频解析与原画下载
    └── download_xhs_batch.py   # 小红书短链批量解析与抓取
```

---

## 🚀 快速上手

### 1. 环境依赖

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/)（需已加入系统 PATH 环境变量）
- 安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
playwright install chromium
```

### 2. 常用操作指令

#### A. 剪贴板监听随剪随下（最推荐）
在日常浏览各平台配药视频时，复制分享链接即可全自动下载入库：
```powershell
python download_nurse_pov.py --watch
# 或通过 main.py：
python main.py social --watch
```

#### B. 直接下载单条或多条链接
```powershell
# 支持直接粘贴包含文本的完整分享文案
python main.py social "https://v.douyin.com/xxxxxx/"
python main.py social "https://xhslink.cn/xxxxxx"
python main.py social "https://www.youtube.com/shorts/xxxxxx"

# 从文本文件批量下载
python main.py social --file urls.txt
```

#### C. YouTube 全自动关键词挖掘与批量入库
```powershell
python auto_download_youtube.py --limit 30 --total 50
```

#### D. 小红书博主主页深度抓取
```powershell
python tools/harvest_xhs_creators.py
```

#### E. 跨平台视觉去重与质量分析
```powershell
# 1. 扫描去重报告
python tools/dedup_cross_platform.py --scan

# 2. 画质择优演练
python tools/dedup_cross_platform.py --merge-dry-run

# 3. 自动合并冗余项并移入回收站
python tools/dedup_cross_platform.py --auto-merge
```

#### F. 刷新样本来源档案
```powershell
python tools/generate_creator_table.py
```
> 输出结果将保存至：`data/临床配药样本来源档案.csv`。

### 3. 运行自动化测试

```powershell
python -m pytest
```
