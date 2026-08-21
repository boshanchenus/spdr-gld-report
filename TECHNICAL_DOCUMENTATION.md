# SPDR GLD 周报工具技术维护文档

最后更新：2026-08-12  
当前 APP 版本：1.1（build 2）

> 2026-08-21 新增：钉钉加签机器人通知；发送失败会保留未通知状态并在下次任务重试。此前已实现 iPhone Web App、历史归档、Telegram 可选发送和 GitHub Actions 每日任务。

## 1. 功能与运行结果

本工具从 SPDR 官方接口下载 GLD Historical Archive Excel，识别日期与黄金持仓吨数列，计算最近 6 个自然周的持仓净变化，并生成柱状图。

双击 `GLD Weekly Chart.app` 后，成功时会：

1. 下载最新数据；
2. 更新本地备用数据；
3. 生成 `charts/gld_weekly_net_change.png`；
4. 自动打开图片；
5. 将本次运行详情写入 `charts/gld_weekly_chart.log`。

## 2. 项目结构

```text
SPDR_GLD_Change/
├── GLD Weekly Chart.app/                 # macOS 双击入口
│   └── Contents/MacOS/GLDWeeklyChart     # 启动脚本
├── gld_weekly_chart.py                   # 下载、解析、计算、绘图主程序
├── requirements.txt                      # 固定版本的 Python 依赖
├── docs/                                 # iPhone Web App 与历史报告（GitHub Pages）
├── .github/workflows/                    # 每日生成与网页部署任务
├── SETUP_IPHONE_WEB_APP.md               # 用户开通步骤
├── .venv/                                # 当前可运行的 Python 虚拟环境
├── .matplotlib-cache/                    # Matplotlib 字体缓存
└── charts/
    ├── gld_weekly_net_change.png         # 最新报告图片
    ├── gld_weekly_chart.log              # 最新运行日志
    └── spdr_gld_historical_archive.xlsx  # 最近一次成功下载的数据缓存
```

## 3. 启动链路

```text
双击 APP
  -> GLDWeeklyChart 启动脚本
  -> 检查 Python 解释器及四个必要模块
  -> 执行 gld_weekly_chart.py
  -> 下载 SPDR Excel（最多 3 次，间隔 1 秒、2 秒）
  -> 下载成功：原子更新本地缓存
     下载失败：读取最近一次成功缓存
  -> 解析数据、计算周变化、生成 PNG
  -> 打开 PNG 并显示完成通知
```

启动器优先使用项目内 `.venv/bin/python`。只有其他 Python 同时安装了 `matplotlib`、`openpyxl`、`pandas`、`requests` 四个模块时才会被采用，避免无依赖的系统 Python 被误选。

## 4. 这次修复的内容

此前网络或 SPDR API 临时异常时，程序直接失败；APP 弹窗只显示日志路径，用户无法马上判断原因。本次做了以下加固：

- SPDR 下载失败会自动重试 3 次；
- 每次成功下载后保留一份“最近可用”Excel；
- 网络不可用时自动使用缓存，仍可生成报告；
- 下载内容通过 Excel 结构验证后才会更新缓存，缓存采用临时文件替换，避免错误响应或写入中断损坏已有缓存；
- 启动前验证 Python 及必要依赖，不再盲目回退到系统 Python；
- 失败弹窗直接显示日志最后 8 行，同时保留完整日志；
- AppleScript 参数不再拼接进代码字符串，避免特殊字符造成弹窗脚本错误；
- 添加固定依赖版本文件，方便以后重建环境。

注意：使用缓存时报告可以正常生成，但数据截至缓存文件最后日期。日志中会出现 `using cached workbook` 警告。网络恢复后的下一次运行会自动刷新缓存。

## 5. 日常运行与手工验证

最简单的方式是双击：

```text
GLD Weekly Chart.app
```

终端中直接运行主程序：

```bash
cd /Users/boshanchen/Desktop/MyTools/SPDR_GLD_Change
.venv/bin/python gld_weekly_chart.py
```

指定周数和输出位置：

```bash
.venv/bin/python gld_weekly_chart.py \
  --weeks 8 \
  --output charts/gld_8_weeks.png
```

使用手工下载的 Excel（此模式不访问网络）：

```bash
.venv/bin/python gld_weekly_chart.py \
  --file /绝对路径/historical_archive.xlsx
```

检查环境：

```bash
.venv/bin/python --version
.venv/bin/python -m pip check
zsh -n "GLD Weekly Chart.app/Contents/MacOS/GLDWeeklyChart"
```

## 6. Python 环境恢复

当前环境为 Python 3.8，依赖已验证可用。若 `.venv` 损坏，建议使用 Python 3.11 或当前项目原有的 Python 3.8 重建；不要删除旧环境，先将它改名保留以便回退。

```bash
cd /Users/boshanchen/Desktop/MyTools/SPDR_GLD_Change
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

重建后先从终端运行一次主程序，再双击 APP。`requirements.txt` 当前固定版本如下：

- matplotlib 3.7.5
- openpyxl 3.1.5
- pandas 2.0.3
- requests 2.32.4

## 7. 故障排查

首先查看：

```text
charts/gld_weekly_chart.log
```

常见情况：

| 表现 | 可能原因 | 处理方式 |
|---|---|---|
| 弹出 Python 环境缺失 | `.venv` 损坏或依赖不全 | 按第 6 节重建，或先运行 `pip check` |
| 日志显示使用缓存 | 网络、DNS 或 SPDR API 暂时不可用 | 报告仍可用；网络恢复后再次运行以刷新数据 |
| 下载失败且没有缓存 | 首次运行无网络 | 联网后再运行一次，成功后会建立缓存 |
| 无法识别日期/吨数列 | SPDR 修改了 Excel 表结构 | 检查 Excel 列名，并调整 `_score_date_column` / `_score_tonnes_column` |
| APP 被 macOS 阻止 | 文件被隔离或系统安全策略变化 | 在“系统设置 -> 隐私与安全性”确认提示；不要随意关闭系统安全功能 |
| 图已生成但未弹出 | `open` 或 Finder 的 GUI 会话异常 | 直接打开 `charts/gld_weekly_net_change.png` |

## 8. 数据计算口径

- 周期为周一到周日的自然周；
- 周初持仓取“周一之前最近一个有数据日”的收盘持仓；
- 周末持仓取“周日当天或之前最近一个有数据日”的收盘持仓；
- 周净变化 = 周末持仓 - 周初持仓；
- 官方节假日或周末没有数据时，自动取最近可用日期；
- 默认展示以官方最新数据所在周为结尾的 6 周。

## 9. iPhone Web App 与每日 Telegram 报告

本项目已实现不需要 Apple Developer 会员的替代方案：

```text
GitHub Actions 每日定时触发
  -> 生成最新 PNG
  -> 按 SPDR 数据日期归档到 docs/reports/YYYY-MM-DD.png
  -> 更新 docs/reports.json
  -> 新数据日期时通过 Telegram 发图
  -> GitHub Pages 部署 Web App 和全部历史
```

相关参数：

- 定时配置：`.github/workflows/daily-report.yml`；
- 当前时间：北京时间每天 16:17；
- 首选发送凭据：GitHub Secrets `DINGTALK_WEBHOOK`、`DINGTALK_SECRET`；
- 可选 Telegram：GitHub Secrets `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`；
- 网页地址：GitHub Variable `WEB_APP_URL`；
- Web App：`docs/index.html`；
- 报告清单：`docs/reports.json`。

去重键是官方 Excel 的最新数据日期，而不是任务运行日期。因此周末、节假日或官方尚未更新时不会重复发送相同报告。GitHub Pages 免费个人账户要求公开仓库；报告本身是公开市场数据，机器人 Token 与 Chat ID 必须只保存为 GitHub Secrets。

## 10. 维护注意事项

- 不要移动 APP 而单独留下 Python 项目；当前 APP 会优先寻找它旁边的 `gld_weekly_chart.py`；
- 如果整个项目移动到其他目录，保持 APP、Python 文件、`.venv` 相对位置不变即可；
- `charts/spdr_gld_historical_archive.xlsx` 是离线容错所需文件，不要随意清理；
- 更新依赖前先备份 `.venv` 并做一次真实下载、断网缓存、APP 双击三项验证；
- SPDR 官方接口或 Excel 格式可能变化，不能从技术上保证外部服务永久不变；当前实现保证临时网络故障时尽量继续出图，并在确实无法恢复时给出明确日志。
