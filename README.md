# 第一人称临床配药视频数据集采集、清洗与科学量化评估工具集 (medication-dataset-tools)

一套面向医疗具身智能（Embodied AI）、机器人配药操作学习（Robot Manipulation）、临床动作识别与教学规范的大规模第一人称（POV）及桌面双手配药实操视频自动化检索、采集、时序多锚点质检、跨平台感知哈希排重与量化评估工具库。

---

## 🌟 核心特性与设计哲学

1. **“大道至简”的数据档案管理**：
   - 杜绝多重表格碎片化。核心数据管理高度收敛为两份规范化档案：
     - **[临床配药样本来源档案.csv](data/临床配药样本来源档案.csv)**：宏观总览单表（创作者、涉及平台、视频数量、临床操作特色与药物类型）。
     - **[临床视频科学质量量化评估表.csv](data/临床视频科学质量量化评估表.csv)**：微观样本量化评分单表（时长评级、多帧双手稳定度得分 0-100、拉普拉斯清晰度量化、综合推荐评级）。
2. **科学的机位与双手动作评估准则**：
   - 不死板硬套“必须头戴式（Ego-Helmet）”，全面兼容以标杆样本（如 `video1` 桌面侧向双手特写、`video2` 桌面微俯双手推抽注射器）为代表的高价值操作视角。
   - 核心准则为 **“双手配药实操动作清晰可见、器械交互明确完整”**，坚决剔除纯人像口播、PPT 教程、宠物日常与远景监控。
3. **多时间锚点时序量化质检**：
   - 采用多进程并行（10 核心）在每部视频的 $20\%, 50\%, 80\%$ 时间节点动态解码采样；
   - 融合肤色与医用手套（蓝色/紫色丁腈）色彩空间分割，测算多帧双手稳定度；
   - 运用拉普拉斯二阶微分方差量化画面清晰度，精准捕捉抖动与虚焦。
4. **全平台智能检索与下载**：
   - 覆盖 **抖音 (Douyin)**、**小红书 (XHS)**、**B站 (Bilibili)**、**YouTube (Shorts/Videos)**；
   - 支持剪贴板实时监听随看随粘随下，自动下载原画视频（`.mp4`）、原图封面（`cover.jpg`）、结构化元数据（`info.json`）与抽样关键帧（`frame_sample.jpg`）。
5. **感知哈希（pHash / dHash）全局去重**：
   - 具备全局跨平台去重能力，秒级识别同源搬运与换标题二次重发，支持画质择优合并。

---

## 📁 科学工程目录结构

```text
medication-dataset-tools/
├── main.py                         # 全功能 CLI 统一命令行入口 (search/download/social/auto-search)
├── download_nurse_pov.py           # 剪贴板实时监听与跨平台快捷下载入口
├── auto_download_youtube.py        # YouTube 配药与护理第一视角全自动搜索下载器
├── pytest.ini                      # 单元测试自动发现配置
├── requirements.txt                # 项目依赖清单
├── README.md                       # 工程设计与使用文档
│
├── config/                         # 检索与过滤词库配置
│   └── keywords.txt                # 临床配药核心词库与负向排除词库
│
├── data/                           # 核心规范档案
│   ├── 临床配药样本来源档案.csv     # 【主档案】创作者与样本统计大盘
│   └── 临床视频科学质量量化评估表.csv # 【质检表】全量样本多维量化评估分级表
│
├── src/                            # 核心业务模块
│   ├── downloader.py               # B站批量下载引擎
│   ├── manifest.py                 # 候选列表读写与安全事务
│   ├── search.py                   # B站 API 搜索与关键词候选清洗
│   ├── social_downloader.py        # 抖音 / 小红书 / YouTube / B站 统一解析下载引擎
│   └── social_search.py            # 浏览器会话与自动化搜索模块
│
├── tests/                          # 自动化测试套件
│   └── test_workflow.py            # 核心工作流回归测试 (pytest 100% 通过)
│
└── tools/                          # 专业质检与运维工具箱
    ├── evaluate_clinical_pov.py    # 多核并行视频科学量化评估工具（输出质检表）
    ├── generate_creator_table.py   # 扫描视频目录生成唯一的《临床配药样本来源档案.csv》
    ├── dedup_cross_platform.py     # 跨平台去重与视频感知哈希比对工具
    ├── harvest_xhs_creators.py     # 小红书指定临床护士主页自动化批量采集
    ├── download_single_xhs.py      # 小红书单条视频解析与原画下载
    └── download_xhs_batch.py       # 小红书短链批量解析与抓取
```

---

## 📊 科学量化评估体系说明

根据临床动作识别标准与具身智能数据需求，系统建立了一套可追溯的评分机制：

| 评估维度 | 指标参数与阈值 | 临床与算法意义 |
| :--- | :--- | :--- |
| **时长评级** | • **原子特写 (<15s)**<br>• **标准完整 (15s-300s)**<br>• **超长待切片 (>300s)** | 标定单步动作特写（如单手弹安瓿）与完整配药闭环（启封-溶解-抽吸-排气），超长视频标记待切片。 |
| **双手稳定度得分**<br>(0 - 100分) | • **卓越稳定 [80-100分]**<br>• **良好标准 [50-79分]**<br>• **波动/偏离 [<50分]** | 采样 3 组时序锚点，综合双臂在场率（50分）与操作区面积占比（50分），兼容俯拍第一视角与桌面双手特写。 |
| **清晰度得分**<br>(Laplacian Var) | • **超高清 (≥100)**<br>• **标准清晰 (35-100)**<br>• **严重虚焦 (<35)** | 计算画面二阶微分方差，参照真实病房标杆（`video1`: 59.2, `video2`: 46.1）校准，确保针头与瓶签刻度可辨。 |
| **综合推荐级别** | • **🌟 S级 (黄金双手实操)**<br>• **🟢 A级 (标准双手合格)**<br>• **🔹 B级 (单步微动作特写)**<br>• **🟡 C级 (长流程待切片)** | 为算法训练集直接提供过滤分级标准，目前库内 **S+A 级优质可用率超过 97%**。 |

---

## 🚀 快速上手指令

### 1. 环境依赖

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/)（需已加入系统 PATH 环境变量）
- 安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
playwright install chromium
```

### 2. 常用操作

#### A. 剪贴板监听随剪随下（推荐日常使用）
浏览各大平台时，复制视频分享链接即可在后台静默自动下载并归档：
```powershell
python download_nurse_pov.py --watch
# 或通过统一 CLI：
python main.py social --watch
```

#### B. 直接下载单条或多条链接
```powershell
# 支持直接粘贴包含文字的整段分享文本
python main.py social "https://v.douyin.com/xxxxxx/"
python main.py social "https://xhslink.cn/xxxxxx"
python main.py social "https://www.youtube.com/shorts/xxxxxx"

# 从文本文件批量读取多条链接
python main.py social --file urls.txt
```

#### C. 全自动视频质量评估与打分
一键启动多核并行质检，全量评估视频时长、双手稳定度与清晰度：
```powershell
python tools/evaluate_clinical_pov.py
```
> 运行完毕后自动生成并刷新：`data/临床视频科学质量量化评估表.csv`。

#### D. 刷新创作者大盘档案
```powershell
python tools/generate_creator_table.py
```
> 运行完毕后自动生成并刷新：`data/临床配药样本来源档案.csv`。

#### E. 运行自动化测试
```powershell
python -m pytest
```
