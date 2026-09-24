import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding="utf-8")

ROOTS = [
    Path("D:/下载/第一人称配药实操视频"),
    Path("D:/下载"),
    Path.home() / "Downloads" / "第一人称配药实操视频",
]

features_map = {
    "一朵小花o（涨粉版）": "血透室临床配药、费森尤斯透析管路安装预冲、密闭式血液透析排气、静脉推注",
    "🍀 Lucky(扎针版)": "静脉输液连续溶药加药、治疗台无菌配液、注射器抽吸与静脉穿刺固定",
    "Sally": "安瓿瓶徒手折断溶药、静脉输液加药、注射器抽吸与排气一镜到底",
    "虫虫飞呀": "大输液袋连续加药配制、双人三查七对规范配液、药液连续抽吸与注入",
    "雷哈哈的雷": "西林瓶粉针溶药、急诊科夜班配药实操、肌内注射（IM）药液配制与抽吸",
    "小夏吖（减肥版）": "维生素复合制剂肌内注射配药、免疫球蛋白皮下注射（SC）、转移因子药液抽吸",
    "小赵吖": "儿科微量药液连续配制、头孢类皮试液稀释、静脉留置针穿刺与单手退针固定",
    "知雾.": "病房夜班第一人称配药、多联玻璃安瓿瓶折断、抗生素粉针溶解、静脉推注配制",
    "打针不疼的小晨💉": "无菌治疗台全套规范配药、注射器抽吸排气一镜到底、西林瓶加生理盐水震荡混匀",
    "小棉阳": "中药注射剂（参麦等）复配、抗生素皮试液配制、破伤风脱敏多联注射液抽吸",
    "捞汁鲍鱼🌸": "第一人称视角规范配药、多规格注射器抽药、西林瓶加生理盐水震荡混匀",
    "小刘good": "经典第一视角原创配药实录、双手配合无菌抽吸加药、输液瓶挂架与药液灌注",
    "Q🌈Q": "医院夜班第一人称配药、一镜到底连续配液、多剂量药液抽吸与排气",
    "张十针": "输液管路排气操作、药液连续抽吸注入、静脉留置针穿刺与固定配合",
    "捞汁鲍鱼饭": "高清晰度第一视角配药实录、西林瓶启封与抽取、粉剂溶解震荡全流程",
    "一朵小花oi": "手部特写近距离配药、注射器微量药液精确抽吸、治疗盘无菌操作规范",
    "桃子Mooo": "海外临床标准化配药规范、药瓶酒精棉片消毒擦拭、多规格注射器定量抽取",
    "国文公主岭院区": "三甲医院临床教学标准示范、安瓿瓶砂轮划痕掰断、药液抽吸与防污染操作",
    "养鲁迅的耄耋": "临床治疗室第一视角配药、粉针剂溶解混匀、输液管路连接与静脉输液加药",
    "66c87c6f000000001d033aef": "第一视角玻璃安瓿瓶开启、注射器垂直抽吸排气、小剂量注射液配制一镜到底",
    "freddie queensbridge": "一镜到底多组连续配药、多安瓿瓶抽吸加药、针头无菌单手回套与整理",
    "YouTube精选 (护士弹安瓿瓶/配药)": "海外临床安瓿瓶弹瓶排气、折断技巧与药液快速抽吸",
    "陈小福🐑": "基层乡村医疗临床配药、头孢类抗生素溶解、雷尼替丁微量加药",
    "旺旺穗冰冰": "第一人称视角沉浸式配药一镜到底、注射器抽吸与西林瓶粉剂复配",
    "研究针💉小刘": "急诊门诊应急配药、局部创伤消炎药物抽吸、肌内注射（IM）药液配制",
    "崔小护vlog": "病区临床日常配液加药、多组药物连续配置、注射器排气与查对",
    "我扎针💉不疼": "原声沉浸式无菌配药加药、呼吸道抗病毒与解热注射药物调配",
    "✿✧世芳": "临床全流程配药实操、粉针剂快速振荡混匀、肌内注射药液配制",
    "鸽子按时下班": "天麻注射液与头孢类抗生素规范溶解、注射器定量抽吸配液",
    "福福大王来也": "特殊专科注射液高精度配置、静脉输液港维护与专用药物推注",
    "每天都很困": "大分子静脉营养液（脂肪乳等）配制、输液管路无菌连接",
    "李开心": "第一人称病房规范配药实操、药瓶消毒与注射器药液抽吸",
    "女 亭": "第一视角玻璃安瓿瓶折断、常规注射液无菌抽取与排气",
    "贝贝南瓜": "病房常规输液连续加药、多联药液规范配制与混匀",
    "王懿懿": "临床护士沉浸式配药一镜到底、玻璃安瓿瓶与注射器细致操作",
    "木子李": "治疗台标准化加药配液、无菌盘器械规整与药液配制",
    "一只社区喵喵": "社区医疗机构第一视角配药、小剂量药液抽吸与溶解",
    "叁叁": "病区护士实录配药、输液袋连续加药与输液器连接",
    "禾禾不加班": "小诊所第一视角规范配药、皮试药液配制与稀释、注射器抽取西林瓶粉针",
    "小芠": "临床护士沉浸式配药、玻璃安瓿瓶折断与药液精确抽吸",
    "蔡不然": "临床静脉留置针穿刺、肌内注射（屁股针）药液配制、皮试操作与观察",
    "🤧阿Q": "医院夜班第一人称配药、一镜到底连续配液、多剂量药液抽吸与排气",
    "小刘护士": "临床注射配药、多联抗生素注射液抽吸、注射器垂直排气",
}

stats = defaultdict(lambda: {"count": 0, "size_mb": 0.0, "platforms": set(), "titles": []})

all_folders = []
seen_names = set()
for r in ROOTS:
    if r.exists():
        for f in sorted(r.iterdir()):
            if f.is_dir() and not f.name.startswith(".") and f.name not in seen_names:
                all_folders.append(f)
                seen_names.add(f.name)

for folder in all_folders:
    author = "未知"
    title = ""
    duration = 0
    mp4s = list(folder.glob("*.mp4"))
    if not mp4s:
        continue
    video_file = mp4s[0]
    size = sum(f.stat().st_size for f in mp4s) / (1024 * 1024)

    # 优先根据文件夹前缀精准判定平台
    if folder.name.startswith("youtube_"):
        platform = "youtube"
    elif folder.name.startswith("xhs_"):
        platform = "xiaohongshu"
    elif folder.name.startswith("douyin_"):
        platform = "douyin"
    elif folder.name.startswith("BV"):
        platform = "bilibili"
    else:
        platform = "未知"

    info_files = list(folder.glob("*.info.json"))
    if info_files:
        try:
            data = json.loads(info_files[0].read_text(encoding="utf-8"))
            title = data.get("title", "")
            duration = data.get("duration") or data.get("videoDuration") or 0
            if not platform or platform == "未知":
                platform = data.get("platform") or ("bilibili" if "bvid" in data else "douyin")
            if "uploader" in data:
                author = data["uploader"]
            elif "author" in data:
                author = data["author"]
            elif "owner" in data and isinstance(data["owner"], dict):
                author = data["owner"].get("name", "bilibili_user")
        except Exception:
            pass

    if not author or author.strip() == "untitled" or author == "未知":
        parts = folder.name.split(" - ")
        if len(parts) >= 3 and parts[-1].strip() and parts[-1].strip() != "untitled":
            author = parts[-1].strip()
        elif len(parts) == 2 and parts[1].strip() and parts[1].strip() != "untitled":
            author = parts[1].strip()
        else:
            if folder.name.startswith("youtube_"):
                author = "YouTube精选 (护士弹安瓿瓶/配药)"
            elif folder.name.startswith("xhs_"):
                author = "小红书精选护士"
            else:
                author = "临床配药精选"

    if not title:
        parts = folder.name.split(" - ")
        if len(parts) >= 2:
            title = parts[1].strip()
        else:
            title = folder.name

    stats[author]["count"] += 1
    stats[author]["size_mb"] += size
    stats[author]["platforms"].add(str(platform))
    if title:
        stats[author]["titles"].append(title)

PROJECT_DIR = Path(__file__).resolve().parent.parent
data_dir = PROJECT_DIR / "data"
data_dir.mkdir(parents=True, exist_ok=True)

platform_labels = {
    "douyin": "抖音 (Douyin)",
    "bilibili": "B站 (Bilibili)",
    "xiaohongshu": "小红书 (XHS)",
    "youtube": "YouTube",
}

# 严格只保留单一档案表：data/临床配药样本来源档案.csv
target_csv = data_dir / "临床配药样本来源档案.csv"

creator_headers = ["序号", "博主名字", "涉及平台", "视频数量", "临床操作特色与药物类型"]
creator_rows = []
idx = 1
for author, d in sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True):
    feat = features_map.get(author, "第一人称临床配药规范实操")
    plats = " / ".join(platform_labels.get(p, p) for p in sorted(d["platforms"]))
    creator_rows.append([idx, author, plats, d["count"], feat])
    idx += 1

with open(target_csv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(creator_headers)
    writer.writerows(creator_rows)

print(f"✅ 成功生成唯一规范样本档案: {target_csv}")

total_vids = sum(d["count"] for d in stats.values())
total_gb = sum(d["size_mb"] for d in stats.values()) / 1024
print(f"统计汇总: 博主数量: {len(stats)}, 视频总数: {total_vids}, 占用空间: {total_gb:.2f} GB")
