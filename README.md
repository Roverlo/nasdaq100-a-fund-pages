# 纳指100 A 类基金筛选表

这是一个本地生成的纳指100 QDII A 类基金对比表工作区。输出是可直接打开的 HTML：

`C:\ALL_in_H\纳指记录\纳指基金支付宝对比表.html`

## 当前内容

- 基金池：17 支纳指100相关 A / 人民币 A 类基金。
- 当前持有：8 支，合计 `560元`。
- 定投中：7 支，合计 `300元 / 期`。
- 暂停定投：4 支，合计 `220元 / 期`。
- 定投计划是计划现金流，不自动计入当前持仓；只有账户截图、手动确认或交易流水中的已确认成交才更新持仓、成本、市值和收益。
- 页面 tab：主表、持仓定投、长期追踪、梯队评级规则、数据来源。
- `持仓定投` 页的两张明细表都显示 `评级` 列，评级与主表使用同一套梯队评分结果。
- 主表定投状态筛选只保留 `定投中`、`暂停定投`、`候选` 三类；`候选` 包含未定投基金，以及已持有但当前没有定投计划的基金。
- 主表申购状态筛选只保留 `允许申购`、`暂停申购` 两类；`限大额`、`开放申购` 等原始可买状态统一展示为 `允许申购`，具体买入额度继续看 `代销限额` / `直销限额`。
- 主表列顺序按决策优先级排列：排名、定投梯队、基金 / 代码、持仓 / 定投、近3年、近1年、跟踪误差、管理+托管、规模、买入费率、免赎回费门槛、申购状态、代销限额、直销限额、费率项目、卖出规则、日涨跌、定投状态。

## 文件说明

- `generate_nasdaq_fund_table.py`：生成脚本和数据配置，页面样式、交互、持仓、定投、评分都在这里维护。
- `纳指基金支付宝对比表.html`：生成后的浏览器页面。
- `nasdaq_fund_snapshot.json`：抓取结果、评分结果、持仓和定投快照。
- `portfolio_tracking.json`：长期追踪记录，保存跨天、跨周、跨月的持仓、市值、收益和收益率。
- `data/nasdaq_funds.db`：SQLite 长期数据层，保存基金、每日主表快照、评级、持仓、定投和未来交易流水。
- `data/schema.sql`：SQLite 表结构和视图定义。
- `data/examples.sql`：用于学习和排查的常用 SQL 查询示例。
- `sync_sqlite_db.py`：把当前 JSON 快照同步进 SQLite 的脚本。
- `direct_limits.json`：直销限额的人工/AI 核实结果。
- `direct_limit_candidates.json`：候选公告，不代表已确认限额。
- `AGENTS.md`：给后续 Codex 维护本项目用的规则。

## 常用命令

在 PowerShell 中运行：

```powershell
python "C:\ALL_in_H\纳指记录\refresh_all.py"
```

`refresh_all.py` 是本地和 GitHub Actions 共用的完整刷新入口，会依次执行：编译生成器、抓取并生成主表、更新长期追踪当日记录、准备 `docs/` 发布页、同步 SQLite 数据库、运行结构一致性校验和抓取健康校验。

如需单独调试生成器：

```powershell
python -m py_compile "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py"
python "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" --output-dir "C:\ALL_in_H\纳指记录"
python "C:\ALL_in_H\纳指记录\prepare_github_pages.py"
python "C:\ALL_in_H\纳指记录\sync_sqlite_db.py"
python "C:\ALL_in_H\纳指记录\validate_refresh_outputs.py"
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
python "C:\ALL_in_H\纳指记录\prepare_github_pages.py"
```

输出说明：

- `docs/index.html`：公开版基金池页面，保留 `长期追踪` 图表；移除 `持仓 / 定投`、`定投状态`、`持仓定投` 明细和可编辑控件。
- `docs/portfolio.html`：公开完整页面，包含主表、持仓定投、长期追踪、梯队评级规则和数据来源，不再需要密钥。

## 自动刷新

GitHub Actions 工作流位于 `.github/workflows/refresh.yml`。它每天按北京时间刷新 3 次：

- `08:45`：覆盖国内基金接口和公告的早间更新。
- `16:45`：覆盖国内交易日白天更新后的状态、限额和规模变化。
- `23:15`：覆盖晚间公告、QDII/海外市场相关数据更新窗口。

每次自动任务都会运行 `python refresh_all.py`。校验通过后才会进入提交判断；如果主表、快照、长期追踪或发布页之间不一致，或者本次基础行情、费率赎回、跟踪误差抓取不是全基金池全部成功，任务会失败，不会静默发布半更新页面。

`should_commit_refresh.py` 会在自动提交前过滤纯时间戳变化。如果只变了 `generated_at`、`recorded_at` 或页面上的“数据更新”时间，而基金业务数据没有变化，GitHub Actions 会跳过提交，避免每天制造 3 个低价值 commit。

`validate_refresh_outputs.py` 是发布前的结构守门：

- 完整页必须保留主表、持仓定投、长期追踪、梯队评级规则、数据来源；公开首页不应带回私有的持仓定投 tab 或定投状态筛选。
- 完整页的定投状态筛选只能是 `定投中`、`暂停定投`、`候选`；公开首页没有定投状态筛选。
- 完整页和公开首页的申购状态筛选都只能是 `允许申购`、`暂停申购`。
- 快照中的每只基金也必须落在上述规范状态内，原始接口文案只保存在 `subscription_status_raw`。

## SQLite 数据层

第四阶段已经接入 SQLite。当前定位是：`nasdaq_fund_snapshot.json` 和 `portfolio_tracking.json` 继续作为静态页面生成输入，`data/nasdaq_funds.db` 作为长期结构化查询、学习数据库和未来扩展交易流水的存储层。

刷新入口：

```powershell
python "C:\ALL_in_H\纳指记录\sync_sqlite_db.py"
```

完整刷新时不需要单独运行它，`refresh_all.py` 会自动调用。数据库文件会随仓库提交，因此 GitHub Actions 每次业务数据发生变化时也会同步一份 SQLite 到 GitHub 仓库；纯时间戳变化会被提交保护过滤。

核心表：

- `funds`：基金基础信息。
- `refresh_runs`：按日期记录抓取健康状态。
- `scoring_models`：当天评级模型、权重和规则。
- `fund_daily_snapshots`：每天每只基金的主表字段。
- `score_snapshots`：每天每只基金的评级、分数、排名。
- `portfolio_records`：每天组合级持仓、定投、市值、收益。
- `portfolio_positions`：每天每只基金的持仓、市值、收益和评级。
- `auto_invest_plans`：每天每只基金的定投状态、金额、频率、原始下次扣款日和按中国内地基金业务日调整后的预计扣款日。
- `transactions`：预留的交易流水表，后续可记录已确认买入、卖出、分红、费用等明细；计划定投本身不要直接写成已成交流水。

常用视图：

- `v_latest_fund_scores`：最新主表评级。
- `v_portfolio_latest_positions`：最新持仓和定投。
- `v_monthly_portfolio_summary`：月度组合汇总。
- `v_active_auto_invest_latest`：当前定投中的基金。

学习 SQL 时可以先看：

```text
C:\ALL_in_H\纳指记录\data\examples.sql
```

## 修改持仓和定投

在 `generate_nasdaq_fund_table.py` 顶部维护这些常量：

- `HOLDING_AMOUNTS`：当前持有金额。
- `AUTO_INVEST_AMOUNTS`：进行中定投金额。
- `PAUSED_AUTO_INVEST_AMOUNTS`：暂停定投金额。
- `AUTO_INVEST_FREQUENCY` 和 `AUTO_INVEST_NEXT_DEBIT_DATE`：定投频率和用户/平台显示的下次扣款日。

当前口径：

- 持有合计：`560元`。
- 定投中合计：`300元 / 期`，其中万家 `019441=200元 / 期`。
- 暂停定投合计：`220元 / 期`。
- `AUTO_INVEST_NEXT_DEBIT_BUSINESS_DATE` 由脚本按中国内地公募基金业务日估算，会排除周末和国务院办公厅公布的 2026 年法定节假日。QDII 还可能受海外市场休市、基金公司暂停申购、额度和平台扣款状态影响，最终仍以支付宝/基金公司订单页为准。
- 定投金额是“下一次计划现金流”，不是“当前已持仓金额”。不要把 `300元 / 期` 自动加进 `holding_plan.holding_total` 或 `portfolio_records.holding_total`；只有确认扣款/成交后，才通过用户截图、手动修改常量或未来 `transactions` 流水更新持仓。

改完后重新生成 HTML，并检查 `nasdaq_fund_snapshot.json` 中：

- `holding_plan.holding_total`
- `auto_invest_plan.active_total`
- `auto_invest_plan.paused_total`
- `auto_invest_plan.next_debit_business_date`
- `auto_invest_plan.cashflow_policy`

## 浏览器内手动编辑

`持仓定投` tab 支持直接点击编辑：

- 点击金额：打开页面浮层金额编辑器，回车或点确定后更新。
- 点击定投状态：打开自定义状态菜单，选择 `定投中`、`暂停定投` 或 `候选`；`候选` 就是没有进行中/暂停计划时的观察状态。
- 页面会即时更新主表的 `持仓 / 定投` 列、两张明细表和标题总额。

这些手动修改保存在当前浏览器的 `localStorage`，键名是 `nasdaqFundPortfolioStateV1`。刷新页面仍会保留，但重新换浏览器或清空站点数据会丢失。

如果要把手动修改变成长期默认值，需要同步回 `generate_nasdaq_fund_table.py` 里的持仓/定投常量，然后重新生成 HTML。

## 长期追踪

`长期追踪` tab 读取 `portfolio_tracking.json`，展示资产轨迹、收益轨迹、持仓结构、追踪快照和基金级明细。设计参考 `nexu-io/open-design` 的单页 artifact / dashboard 思路，以及 Ghostfolio、Wealthfolio、Portfolio Performance 这类投资追踪工具的长期组合视角。

生成脚本会维护长期记录，但不会一天追加 3 条重复快照：同一个北京时间日期内刷新时，只更新当天记录；当北京时间日期变化时，才追加新记录。自动更新字段包括评级、评分、持仓金额、进行中定投和暂停定投；真实市值、成本、收益、收益率等个人字段会被保留，不会被刷新覆盖。

当前基线只包含已知的持仓金额和定投计划；真实市值、累计收益、收益率需要以后按支付宝/账户截图或手动记录写入 `portfolio_tracking.json`。未知值保持 `null`，页面显示为 `--`，图表也不会伪造趋势，不要用基金阶段涨幅替代个人实际收益。

长期追踪里，`active_auto_invest_total` 只表示当日仍在执行的计划定投额度。它可以帮助判断未来现金流压力，但不会自动滚入 `holding_total`。每条 `portfolio_tracking.json` 日记录都要保存当时的 `auto_invest_frequency`、`next_debit_date`、`next_debit_business_date` 和 `cashflow_policy`，方便几年后还原当时口径。后续如果实现交易流水，推荐流程是：定投计划生成预计事件，实际扣款/确认成交后再写入 `transactions`，然后由确认流水或用户截图更新持仓和成本。

发布 GitHub Pages 时：

- `docs/index.html`：公开页保留长期追踪图表，方便分享长期组合变化；仍移除 `持仓定投` 的编辑明细。
- `docs/portfolio.html`：公开完整页保留持仓、定投和长期追踪，不再加密。

## 页面验证注意

如果在 Codex in-app browser 里打开了页面评论/标注，评论层可能覆盖页面按钮。表现是自动化点击 tab 或按钮没有反应，但控制台没有报错，命中元素可能是 `codex-browser-sidebar-comments-root`。这种情况下先用 HTML/DOM 结构检查确认生成结果，或关闭评论层后再做交互验证。

## 数据口径

- `代销限额`：支付宝/蚂蚁基金等代销渠道限额。
- `直销限额`：基金公司直销渠道限额。
- `管理+托管`：管理费率 + 托管费率。
- 销售服务费单独展示，不并入 `管理+托管`。
- 梯队评级是当前基金池内相对排序，不是收益预测。
- 当前评级权重：近3年收益 35%、近1年收益 20%、跟踪误差 20%、管理+托管 15%、基金规模 6%、买入费率 2%、赎回灵活性 2%。
- `申购状态`、`代销限额`、`直销限额` 只作为筛选和交易执行信息，不参与梯队评级。`subscription_status_raw` 保留接口原文，例如 `限大额(单日投资上限10元)`；页面规范状态只显示 `允许申购` / `暂停申购`。

## Git 状态

本目录当前是有效 Git 仓库，远端为：

```text
https://github.com/Roverlo/nasdaq100-a-fund-pages.git
```

如果 GitHub 推送直连失败，可按 `AGENTS.md` 里的代理说明临时加 `-c http.proxy=http://127.0.0.1:10808 -c https.proxy=http://127.0.0.1:10808`。
