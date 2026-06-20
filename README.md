# 纳指100 A 类基金筛选表

这是一个本地生成的纳指100 QDII A 类基金对比表工作区。输出是可直接打开的 HTML：

`C:\ALL_in_H\纳指记录\纳指基金支付宝对比表.html`

## 当前内容

- 基金池：16 支纳指100相关 A / 人民币 A 类基金。
- 当前持有：8 支，合计 `560元`。
- 定投中：7 支，合计 `300元 / 期`。
- 暂停定投：4 支，合计 `220元 / 期`。
- 页面 tab：主表、持仓定投、长期追踪、梯队评级规则、数据来源。
- `持仓定投` 页的两张明细表都显示 `评级` 列，评级与主表使用同一套梯队评分结果。
- 主表列顺序按决策优先级排列：排名、定投梯队、基金 / 代码、持仓 / 定投、近3年、近1年、跟踪误差、管理+托管、规模、买入费率、免赎回费门槛、申购状态、代销限额、直销限额、费率项目、卖出规则、日涨跌、定投状态。

## 文件说明

- `generate_nasdaq_fund_table.py`：生成脚本和数据配置，页面样式、交互、持仓、定投、评分都在这里维护。
- `纳指基金支付宝对比表.html`：生成后的浏览器页面。
- `nasdaq_fund_snapshot.json`：抓取结果、评分结果、持仓和定投快照。
- `portfolio_tracking.json`：长期追踪记录，保存跨天、跨周、跨月的持仓、市值、收益和收益率。
- `direct_limits.json`：直销限额的人工/AI 核实结果。
- `direct_limit_candidates.json`：候选公告，不代表已确认限额。
- `AGENTS.md`：给后续 Codex 维护本项目用的规则。

## 常用命令

在 PowerShell 中运行：

```powershell
python -m py_compile "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py"
python "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" --output-dir "C:\ALL_in_H\纳指记录"
```

同步到本地 skill：

```powershell
Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force
python -m py_compile "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py"
```

生成直销限额候选公告：

```powershell
python "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" --output-dir "C:\ALL_in_H\纳指记录" --write-direct-limit-candidates
```

## 本地容器预览

内置浏览器对 `file://` 页面会限制自动刷新和 DOM 检查。开发和调样式时优先用 Docker 静态服务：

```powershell
cd C:\ALL_in_H\纳指记录
docker compose up -d
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

容器使用本机已有的 `python:3.11-slim-bookworm` 镜像和 bind mount 读取当前目录，`serve_static.py` 会把根路径 `/` 直接映射到生成的 HTML，并禁用浏览器缓存。重新运行 `generate_nasdaq_fund_table.py` 后刷新页面即可看到新 HTML；通常不需要重建镜像。

停止预览：

```powershell
docker compose down
```

## GitHub Pages 发布

当前公开发布仓库：

```text
https://github.com/Roverlo/nasdaq100-a-fund-pages
https://roverlo.github.io/nasdaq100-a-fund-pages/
```

发布目录是仓库 `main` 分支的 `/docs`。本地用 `prepare_github_pages.py` 生成：

```powershell
$env:PORTFOLIO_PAGE_PASSWORD="换成你的长密钥"
python "C:\ALL_in_H\纳指记录\prepare_github_pages.py"
```

输出说明：

- `docs/index.html`：公开版基金池页面，保留 `长期追踪` 图表；移除 `持仓 / 定投`、`定投状态`、`持仓定投` 明细和可编辑私密控件。
- `docs/portfolio.html`：用 Staticrypt 加密后的完整私密页面，输入密钥后在浏览器本地解密查看。

当前临时密钥保存在本地 `tmp/pages_password.txt`，不要提交到 GitHub。

## 修改持仓和定投

在 `generate_nasdaq_fund_table.py` 顶部维护这些常量：

- `HOLDING_AMOUNTS`：当前持有金额。
- `AUTO_INVEST_AMOUNTS`：进行中定投金额。
- `PAUSED_AUTO_INVEST_AMOUNTS`：暂停定投金额。
- `AUTO_INVEST_FREQUENCY` 和 `AUTO_INVEST_NEXT_DEBIT_DATE`：定投频率和下次扣款日。

当前口径：

- 持有合计：`560元`。
- 定投中合计：`300元 / 期`，其中万家 `019441=200元 / 期`。
- 暂停定投合计：`220元 / 期`。

改完后重新生成 HTML，并检查 `nasdaq_fund_snapshot.json` 中：

- `holding_plan.holding_total`
- `auto_invest_plan.active_total`
- `auto_invest_plan.paused_total`

## 浏览器内手动编辑

`持仓定投` tab 支持直接点击编辑：

- 点击金额：打开页面浮层金额编辑器，回车或点确定后更新。
- 点击定投状态：打开自定义状态菜单，选择 `定投中`、`暂停定投` 或无定投状态。
- 页面会即时更新主表的 `持仓 / 定投` 列、两张明细表和标题总额。

这些手动修改保存在当前浏览器的 `localStorage`，键名是 `nasdaqFundPortfolioStateV1`。刷新页面仍会保留，但重新换浏览器或清空站点数据会丢失。

如果要把手动修改变成长期默认值，需要同步回 `generate_nasdaq_fund_table.py` 里的持仓/定投常量，然后重新生成 HTML。

## 长期追踪

`长期追踪` tab 读取 `portfolio_tracking.json`，展示资产轨迹、收益轨迹、持仓结构、追踪快照和基金级明细。设计参考 `nexu-io/open-design` 的单页 artifact / dashboard 思路，以及 Ghostfolio、Wealthfolio、Portfolio Performance 这类投资追踪工具的长期组合视角。

生成脚本只在文件不存在或没有记录时写入一条初始基线，不会每次刷新自动追加，避免长期记录里堆积重复快照。

当前基线只包含已知的持仓金额和定投计划；真实市值、累计收益、收益率需要以后按支付宝/账户截图或手动记录写入 `portfolio_tracking.json`。未知值保持 `null`，页面显示为 `--`，图表也不会伪造趋势，不要用基金阶段涨幅替代个人实际收益。

发布 GitHub Pages 时：

- `docs/index.html`：公开页保留长期追踪图表，方便分享长期组合变化；仍移除 `持仓定投` 的编辑明细。
- `docs/portfolio.html`：加密完整页保留持仓、定投和长期追踪。

## 页面验证注意

如果在 Codex in-app browser 里打开了页面评论/标注，评论层可能覆盖页面按钮。表现是自动化点击 tab 或按钮没有反应，但控制台没有报错，命中元素可能是 `codex-browser-sidebar-comments-root`。这种情况下先用 HTML/DOM 结构检查确认生成结果，或关闭评论层后再做交互验证。

## 数据口径

- `代销限额`：支付宝/蚂蚁基金等代销渠道限额。
- `直销限额`：基金公司直销渠道限额。
- `管理+托管`：管理费率 + 托管费率。
- 销售服务费单独展示，不并入 `管理+托管`。
- 梯队评级是当前基金池内相对排序，不是收益预测。
- 当前评级权重：近3年收益 35%、近1年收益 20%、跟踪误差 20%、管理+托管 15%、基金规模 6%、买入费率 2%、赎回灵活性 2%。
- `申购状态`、`代销限额`、`直销限额` 只作为筛选和交易执行信息，不参与梯队评级。

## Git 状态

本目录当前不是有效 Git 仓库。虽然有 `.git` 文件夹，但 `git rev-parse --is-inside-work-tree` 返回 `fatal: not a git repository`。

因此当前维护是本地文件更新；如需提交和推送，需要先修复或重新初始化 Git。
