# Codex 维护规则

本目录是纳指100 QDII A 类基金对比表的本地工作区，主要产物是单文件 HTML 表格和 GitHub Pages 公开页。

## 工作原则

- 终端是 Windows PowerShell。不要使用 Bash heredoc，例如 `python - <<'PY'`；需要内联 Python 时用 PowerShell here-string：`@' ... '@ | python -`。
- 默认使用 `nasdaq-fund-table` skill。动手前先读 `C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\SKILL.md`，但本文件里的项目口径优先级更高。
- 修改页面时改 `generate_nasdaq_fund_table.py`，不要直接改生成后的 `纳指基金支付宝对比表.html`，否则下次刷新数据会丢失改动。
- 每次改完生成脚本后，同步到 skill 脚本：
  `Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force`
- 当前目录是有效 Git 仓库，远端为 `https://github.com/Roverlo/nasdaq100-a-fund-pages.git`。每次代码更新后按用户规则提交并推送；推送直连失败时，用本机代理 `127.0.0.1:10808` 临时配置 Git 命令。
- 调试页面优先使用本地容器预览，不要再依赖 `file://`：`docker compose up -d` 后访问 `http://127.0.0.1:8765/`。Compose 使用本机已有的 `python:3.11-slim-bookworm` 镜像，通过 bind mount 暴露当前目录，`serve_static.py` 将根路径映射到生成 HTML 并禁用缓存，重新生成 HTML 后刷新浏览器即可看到更新。

## 当前用户口径

- 项目不再记录用户个人持仓金额、定投金额、累计投入、下次扣款日、交易流水、收益、市值、成本、收益率或任何自动账本推算。
- 金额、成交、持仓、收益和真实定投扣款状态以支付宝或基金公司交易页为准；本项目不要尝试替代支付宝账本。
- 只保留“哪些基金定投中、哪些暂停定投、哪些只是候选”的状态标签。状态只能是 `定投中`、`暂停定投`、`候选`。
- 当前状态常量只维护 `AUTO_INVESTING_CODES`、`PAUSED_AUTO_INVESTING_CODES` 和 `AUTO_INVEST_STATUS_SUMMARY`。不要恢复 `HOLDING_AMOUNTS`、`AUTO_INVEST_AMOUNTS`、`PAUSED_AUTO_INVEST_AMOUNTS`、`AUTO_INVEST_SCREENSHOT_SUMMARY`、`AUTO_INVEST_FREQUENCY`、`AUTO_INVEST_NEXT_*`、`projected_*` 或现金流账本字段。
- 当前已确认 `定投中`：`019172`、`040046`、`019441`、`016452`、`270042`、`019547`、`019524`、`018966`、`019736`、`000834`、`539001`。
- 当前已确认 `暂停定投`：暂无。不要根据旧截图里未展开的暂停数量臆造具体基金。
- 国泰纳斯达克100 `160213` 已加入基金池；它和其他非定投基金一样，只在主表展示公开申购状态、限额、费率、评分和 `候选` 状态。
- 只保留纳指100相关 A / 人民币 A 类长期观察视角；非 A 类份额不要加入主表。

## 核心文件

- `generate_nasdaq_fund_table.py`：唯一应编辑的生成脚本，含基金池、公开数据抓取、定投状态标签、评分、样式和交互。
- `纳指基金支付宝对比表.html`：生成产物，浏览器查看用，不手工编辑。
- `nasdaq_fund_snapshot.json`：本次抓取和计算快照，用于核对公开字段、评分、申购状态、限额和定投状态标签。
- `portfolio_tracking.json`：长期状态快照。只按北京时间做“同日更新、跨日追加”的状态记录，不保存个人金额、交易、收益或账本推算。
- `data/nasdaq_funds.db`：SQLite 长期数据层，由 `sync_sqlite_db.py` 从 JSON 同步生成；保存公开数据、评分、执行信息变化和状态标签。`transactions` 表如因兼容保留，必须为空，不写入个人交易流水。
- `data/schema.sql`：SQLite 表和视图定义。改数据库结构时优先改这里，再让 `sync_sqlite_db.py` 应用；执行信息变化视图是 `v_recent_execution_alerts`。
- `data/examples.sql`：学习和排查用 SQL 示例，只写公开数据、评分和状态查询示例。
- `sync_sqlite_db.py`：数据库同步脚本，完整刷新入口会自动调用。
- `direct_limits.json`：人工或 AI 从基金公司公告核实后的直销限额覆盖表。
- `direct_limit_candidates.json`：候选公告列表，不等于已核实直销限额。

## 数据和评分

- `代销限额` 对应支付宝/蚂蚁基金等代销平台限额；`直销限额` 对应基金公司直销渠道限额。不要混成一列。
- “哪种数据最真实”的优先级：实际交易页当前显示和下单结果 > 基金公司官网/公告/产品状态 > 官方披露镜像 PDF > 东方财富/天天基金等第三方接口 > 脚本回退值。申购状态、代销限额这类交易执行数据必须优先按交易入口事实；收益、规模、费率、跟踪误差可按公开接口自动刷新但要通过 `source_health` 校验。
- 如果用户截图或口述的支付宝/代销交易页限额与东方财富 `SGZT` 原文冲突，代销限额必须以实际交易入口为准，并写入 `generate_nasdaq_fund_table.py` 的 `AGENCY_LIMIT_OVERRIDES`；东方财富原文继续保存在 `subscription_status_raw`，不能再次覆盖交易入口校准值。当前万家 `019441` 代销限额按用户 2026-06-22 反馈校准为 `50`。
- `申购状态` 页面规范值只有 `允许申购` 和 `暂停申购`。东方财富 `SGZT` 原文如 `限大额(...)`、`开放申购` 应归一为 `允许申购`，原文继续保存在 `subscription_status_raw`；具体额度仍由 `代销限额` / `直销限额` 展示。
- `管理+托管` 只等于管理费率 + 托管费率。销售服务费单独展示，不并入主排序列。
- 梯队评级是当前基金池内相对排序，不是收益预测。当前权重为：近3年收益 35%、近1年收益 20%、跟踪误差 20%、管理+托管 15%、基金规模 6%、买入费率 2%、赎回灵活性 2%。
- `申购状态`、`代销限额`、`直销限额` 和定投状态只作为筛选和交易执行信息，不参与梯队评级；不能因为暂停申购、限额低或未定投直接拉低基金质量评分。
- 每次完整刷新都要读取上一版 `nasdaq_fund_snapshot.json`，用本次抓取结果生成 `execution_alerts`。东方财富接口字段 `SGZT`、`daily_limit`、规模和收益属于每天 3 次自动刷新范围；直销限额只有在 `direct_limits.json` 或脚本回退值变化时才会触发对比，不要声称已自动核验基金公司公告。
- 执行信息提示保留 72 小时：限额上调显示绿色 `++`，限额下调显示红色 `--`；`暂停申购 -> 允许申购` 显示绿色恢复申购，`允许申购 -> 暂停申购` 显示红色暂停申购。用户手动/计划层面的 `暂停定投` 必须用黄色，和基金平台 `暂停申购` 的红色区分开。
- 直销限额变化频繁，重要比较前要重新查基金公司公告或官方披露。主表基金不得静默使用 `脚本内置回退值` 当作已核实直销限额；如果暂停申购导致直销限额无法核验，应在 `direct_limits.json` 明确写 `limit: null`、来源公告和 `confidence: fallback_unverified`，页面和快照显示待核验。

## 验证流程

改动后至少执行：

```powershell
python "C:\ALL_in_H\纳指记录\refresh_all.py"
Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force
python -m py_compile "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py"
```

`refresh_all.py` 会编译生成器、抓取并生成主表、更新 `portfolio_tracking.json` 当天记录、准备 GitHub Pages 的 `docs/`、同步 `data/nasdaq_funds.db`、编译提交判断脚本、运行 `validate_refresh_outputs.py`。不要跳过这个入口后只手动生成 HTML。

再做结构检查：

- `#main-table` 表头列数应等于每行单元格数。
- 当前主表应为 `18` 列、`17` 行，除非基金池有意变更。
- `nasdaq_fund_snapshot.json` 不应包含 `holding_plan`，每只基金也不应包含个人金额、收益、交易或账本推算字段。
- `nasdaq_fund_snapshot.json.auto_invest_plan` 只应保存状态策略、状态数量、状态代码列表和来源摘要。
- `nasdaq_fund_snapshot.json` 中 `source_health.checks` 应要求基础行情、费率赎回、跟踪误差均为全基金池成功；如果接口不可用导致回退值生成，应让验证失败，不要发布“假刷新”。
- 完整页和公开首页的定投状态筛选必须只有 `定投中`、`暂停定投`、`候选`。
- 完整页和公开首页的申购状态筛选必须只有 `允许申购`、`暂停申购`；如果未来 `prepare_github_pages.py` 重排公开页，也要继续保留这个二分类校验。
- `nasdaq_fund_snapshot.json` 每只基金的 `status` 必须落在 `定投中`、`暂停定投`、`候选`，`subscription_status` 必须落在 `允许申购`、`暂停申购`；原始接口文案只允许进入 `subscription_status_raw`。
- `portfolio_tracking.json` 应存在，最新记录日期应等于当前北京时间日期；最新记录只保存状态数量、状态策略、基金评级、评分和状态。
- `data/nasdaq_funds.db` 应存在，`funds`、`fund_daily_snapshots`、`score_snapshots`、`portfolio_records`、`portfolio_positions`、`auto_invest_plans` 应与最新 JSON 口径一致；`transactions` 可以为空但不得写入个人流水。
- 移动端样式改动后必须专项检查 `数据来源` tab：`source-table` 桌面端第一列有固定宽度，手机端卡片化时要覆盖 `td:first-child { width: auto; }`，并确认代码值如 `019441` 横向单行显示，不要被挤成竖排。

## SQLite 数据规则

- 当前数据库是长期查询和学习层，不替代生成器常量、主表快照和追踪 JSON 的源头地位。
- `portfolio_records` 只保存状态数量、状态策略和日期；不保存持仓总额、市值、成本、收益或收益率。
- `portfolio_positions` 只保存每只基金当日状态、评级和评分；不保存个人持仓或定投金额。
- `auto_invest_plans` 只保存每只基金当日状态；不保存金额、频率或下次扣款日。
- `transactions` 如因旧结构兼容保留，只能为空。不要把真实买卖、定投扣款、分红、费用或支付宝流水写入本项目。
- `sync_sqlite_db.py` 对 `generated_at`、`recorded_at` 做低噪声处理：同一天业务数据没变时，不应仅因时间戳导致 SQLite 文件变化，避免 GitHub Actions 每天 3 次无意义提交。
- 要学习数据库或排查数据时，优先用 `data/examples.sql` 和这些视图：`v_latest_fund_scores`、`v_portfolio_latest_positions`、`v_monthly_portfolio_summary`、`v_active_auto_invest_latest`。

## 自动刷新

- GitHub Actions 工作流：`.github/workflows/refresh.yml`。
- 每天按北京时间 `08:45`、`16:45`、`23:15` 自动刷新，对应 UTC cron 为 `45 0,8 * * *` 和 `15 15 * * *`。
- 自动任务必须运行 `python refresh_all.py`，校验通过后再运行 `should_commit_refresh.py` 判断是否存在业务数据变化；只有纯时间戳变化时不提交，避免每天 3 次无意义 commit。
- 生成页内置发布版本轮询：GitHub Pages 页面每 5 分钟、窗口重新获得焦点、页面重新可见时检查当前 URL 是否已发布新版 HTML。只有检测到新版 `fund-page-generated-at` 大于当前页面时才自动 `location.reload()`，让标题更新时间和所有指标一起更新；不要做只改页面时间、不换业务数据的前端假刷新。
- 自动刷新产生的申购状态/限额变化要写入 `nasdaq_fund_snapshot.json.execution_alerts`，同步渲染到完整页和公开页，并同步进 SQLite `execution_alerts`；`validate_refresh_outputs.py` 应继续校验该结构，防止快照和页面提示脱节。
- `nasdaq_fund_snapshot.json.execution_alerts` 和页面角标只保留短窗口提醒；SQLite `execution_alerts` 要追加/幂等更新已发现事件，用 `detected_at + code + alert_type` 去重，保留历史追溯记录。

## UI 偏好

- 页面要紧凑、实用、可排序；不要加使用说明、解释性大段文字或无用 summary cards。
- 主表、定投状态、长期追踪、梯队评级规则、数据来源作为 tab 展示。
- 主表列顺序按决策优先级排列：`排名`、`定投梯队`、`基金 / 代码`、`状态摘要`、`近3年`、`近1年`、`跟踪误差`、`管理+托管`、`规模`、`买入费率`、`免赎回费门槛`、`申购状态`、`代销限额`、`直销限额`、`费率项目`、`卖出规则`、`日涨跌`、`定投状态`。默认排序必须落在 `定投梯队`，不要默认按基金名称或交易状态排序。
- `定投状态` tab 只保留状态明细表和标题右侧数量，不放持仓金额、定投金额、下次扣款日、收益、当前持有表、说明文字或 summary cards。
- `定投状态` tab 的明细表要在 `基金` 后展示 `评级` 列；评级必须复用主表同一套 `score_cards` / `investing_tier` / `investing_score`，不要做状态专属评分。
- `定投状态` tab 的 `评级`、`状态` 表头应支持点击排序，并显示和主表一致的排序箭头；排序只作用于状态明细表，不应改动主表排序。手机端会隐藏表头做卡片化布局，必须保留表上方的移动端排序按钮。
- `定投状态` tab 支持点击状态做浏览器内手动编辑。状态用自定义浮层菜单，不要用会撑开表格的原生 inline input/select。编辑结果写入 `localStorage` 的 `nasdaqFundPortfolioStateV1`，会即时刷新主表、状态明细表和标题数量，但不会自动写回 `generate_nasdaq_fund_table.py`。
- 主表和状态编辑只暴露三类：`定投中`、`暂停定投`、`候选`。`候选` 包含未定投基金和已持有但当前无定投计划的基金；不要再引入 `已持有`、`新增定投`、`定投中（含新增）` 作为筛选选项。
- 主表申购状态筛选只暴露两类：`允许申购`、`暂停申购`。不要再把 `限大额`、`开放申购` 做成筛选选项；限额信息已经有单独列。
- 如果用户确认浏览器内编辑结果要长期固化，只同步 `AUTO_INVESTING_CODES`、`PAUSED_AUTO_INVESTING_CODES` 和 `AUTO_INVEST_STATUS_SUMMARY`，再重新生成 HTML 和快照；不要恢复金额常量。
- `长期追踪` tab 只展示状态追踪视角：一行关键数量、年度状态摘要、基金状态明细、快照时间轴。不放资产轨迹图、收益轨迹图、持仓结构条或个人收益字段。
- GitHub Pages 当前不再需要密钥：`docs/index.html` 是轻量公开页，`docs/portfolio.html` 是公开完整页。不要恢复 Staticrypt 或密码页，除非用户明确要求重新加密。
- 公开首页可以保留主表定投状态列和筛选，但不应包含可编辑的状态明细 tab 或本地编辑浮层。
- 表格布局尽量基于容器自适应，不要为了单个屏幕写死宽度。
- 做移动端 review 时逐个 tab 检查真实可见交互，不要只看 DOM 里有没有桌面控件；如果表头被隐藏，对应排序/筛选入口要有手机端替代控件，并纳入 `validate_refresh_outputs.py`。
- 桌面表格列宽规则可能在移动端卡片化后继续作用到单元格；给辅助表新增固定列宽时，必须在移动端 media query 里确认是否需要覆盖，尤其是 `数据来源` 这种 label/value 卡片表。
- in-app browser 对 `file://` 页面可能禁止自动刷新或评估；遇到浏览器策略阻止时，用 HTML/JSON 结构检查验证，并提示用户手动刷新。
- in-app browser 对 `http://127.0.0.1:8765/` 可用于自动 reload、DOM 检查和截图验证；容器未启动时先启动 `nasdaq-fund-table` 服务。
- 如果浏览器评论/标注层开启，自动化点击可能命中 `codex-browser-sidebar-comments-root` 而不是页面按钮。遇到 tab/button 自动点击无效但控制台无报错时，先做 hit-test 或结构检查，必要时让用户关闭评论层后再验证，不要误判为页面脚本坏了。
