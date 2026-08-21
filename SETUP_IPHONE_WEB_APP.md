# iPhone GLD Web App 开通步骤

代码已经准备好。本文件只列出需要你亲自完成的账号和网页操作；机器人令牌不要发给任何人，也不要写进代码。

## 一、最终效果

- GitHub 每天北京时间 16:17 自动运行；
- 有新的 SPDR 官方数据日期时，保存一张历史图片并通过 Telegram 发到手机；
- 没有新数据时不重复发送；
- GitHub Pages 提供一个可添加到 iPhone 主屏幕的 Web App；
- Web App 首页显示最新报告，下面可以查看全部历史图片；
- 不需要 Apple Developer Program，也不需要每年 99 美元。

## 二、准备 GitHub 仓库

### 1. 在 GitHub 网站创建仓库

登录 GitHub，创建一个新仓库，例如：

```text
spdr-gld-report
```

如果你使用 GitHub Free，请选择 `Public`：GitHub 免费账户的 Pages 只支持公开仓库。项目代码和 GLD 报告本身不含私人信息；Telegram Token 与 Chat ID 会放在 GitHub Secrets 中，不会公开。不要勾选自动创建 README、`.gitignore` 或 License，因为本地已经有文件。

如果你已有 GitHub Pro，也可以选择 `Private`，但发布出来的 Pages 网站仍是公开访问的。真正的私有 Pages 需要企业方案，不属于本方案的免费范围。

### 2. 把本地代码上传

把下面的 `你的GitHub用户名` 和仓库名换成自己的：

```bash
cd /Users/boshanchen/Desktop/MyTools/SPDR_GLD_Change
git init
git add .
git commit -m "Initial GLD report Web App"
git branch -M main
git remote add origin https://github.com/boshanchenus/spdr-gld-report.git
git push -u origin main
```

如果 GitHub 要求登录，按页面提示使用浏览器授权或 Personal Access Token。不要把密码或 Token 写进项目文件。

### 3. 开启 GitHub Pages

在仓库页面进入：

```text
Settings -> Pages -> Build and deployment -> Source
```

选择：

```text
GitHub Actions
```

然后进入 `Actions`，打开 `Deploy GLD Web App`，点 `Run workflow`。完成后 Pages 页面会显示网站地址，通常是：

```text
https://你的GitHub用户名.github.io/spdr-gld-report/
```

注意：GitHub Pages 网站和 Public 仓库都公开可访问。这个项目只包含公开的 GLD 市场报告，不要把任何令牌、聊天 ID 或私人内容放进项目文件。GitHub Secrets 不会被提交到仓库。

## 三、建立 Telegram 机器人

### 1. 创建机器人并取得 Token

在 iPhone 安装并登录 Telegram，然后搜索官方账号：

```text
@BotFather
```

依次发送：

```text
/newbot
```

按照提示设置机器人名称和以 `bot` 结尾的用户名。BotFather 会返回一段 Bot Token。把它暂存在密码管理器中。

### 2. 让机器人认识你的聊天

在 Telegram 打开刚创建的机器人，点 `Start`，随便发送一句：

```text
hello
```

然后在浏览器打开（把 Token 换成真实值）：

```text
https://api.telegram.org/bot你的Token/getUpdates
```

在返回结果中找到：

```json
"chat": { "id": 123456789 }
```

这个数字就是 `TELEGRAM_CHAT_ID`。取得后可以关闭这个网页。

## 四、把秘密安全地交给 GitHub Actions

在 GitHub 仓库进入：

```text
Settings -> Secrets and variables -> Actions
```

在 `Secrets` 标签创建两个 Repository secret：

| 名称 | 内容 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 给你的完整 Token |
| `TELEGRAM_CHAT_ID` | 上一步获得的聊天数字 ID |

然后切换到 `Variables` 标签，创建：

| 名称 | 内容 |
|---|---|
| `WEB_APP_URL` | GitHub Pages 的完整网址，末尾保留 `/` |

Secrets 不会显示在代码里；不要把它们添加到 `requirements.txt`、MD、Python、Workflow 或 Git commit。

## 五、做第一次完整测试

进入：

```text
GitHub 仓库 -> Actions -> Daily GLD report -> Run workflow
```

第一次执行已有报告日期时，为避免重复消息，程序可能显示：

```text
Telegram skipped: this data date was already published.
```

这属于正常去重。如果希望马上验证 Telegram，可暂时在 GitHub 网页删除 `docs/reports.json` 中最新日期对应的整段记录以及对应 PNG，提交后再手工运行；测试后程序会重新生成它。编辑 JSON 时要注意逗号和括号。

更稳妥的测试方式是在 Mac 终端临时运行，环境变量只对这一条命令有效：

```bash
cd /Users/boshanchen/Desktop/MyTools/SPDR_GLD_Change
TELEGRAM_BOT_TOKEN='你的Token' \
TELEGRAM_CHAT_ID='你的Chat ID' \
WEB_APP_URL='你的Pages网址' \
.venv/bin/python gld_weekly_chart.py \
  --publish-dir /tmp/gld-web-test \
  --send-telegram
```

不要把包含真实 Token 的命令保存进 Shell 脚本、截图或聊天记录。运行后可清除当前终端历史中的对应行。

## 六、添加到 iPhone 主屏幕

1. 必须使用 Safari 打开 GitHub Pages 地址；
2. 点击底部“分享”按钮；
3. 选择“添加到主屏幕”；
4. 名称保留为“GLD 周报”；
5. 点击“添加”。

以后它会像独立 App 一样从桌面全屏打开。Telegram 负责主动把新图片发到手机，Web App 负责查看最新和历史记录。

## 七、修改每日执行时间

当前任务在北京时间每天 `16:17` 运行，配置位于：

```text
.github/workflows/daily-report.yml
```

其中：

```yaml
cron: "17 8 * * *"
timezone: "Asia/Shanghai"
```

表示北京时间 16:17。由于 SPDR 数据通常按美国交易日更新，建议在北京时间下午或晚上运行。GitHub 定时任务可能延迟几分钟，不保证精确到秒。

## 八、以后如何更新代码

本地修改完成后：

```bash
git add .
git commit -m "说明本次修改"
git push
```

只要 `docs/` 发生变化，`Deploy GLD Web App` 会自动更新手机网页。每日任务生成新报告后也会提交历史图片，并触发页面部署。

## 九、常见问题

### Telegram 没收到图片

- 确认已经对机器人点过 `Start`；
- 检查两个 GitHub Secret 名字是否完全一致；
- 打开 Actions 运行日志查看错误；
- 如果日志显示日期已经发布，说明去重生效，不是发送故障。

### Web App 显示旧内容

先点右上角刷新按钮；仍未更新时，查看 GitHub 的 `Deploy GLD Web App` 是否运行成功。

### GitHub Action 无法 push

进入：

```text
Settings -> Actions -> General -> Workflow permissions
```

确认允许 `Read and write permissions`。Workflow 本身也已经声明 `contents: write`。

### 定时任务没准点运行

GitHub 的免费定时任务允许延迟。当前特意安排在每小时第 17 分钟，避开整点高峰。它适合每日更新，但不是严格的实时调度器。
