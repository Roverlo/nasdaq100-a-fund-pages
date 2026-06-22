# Codex 维护规则

本目录是纳指100 QDII A 类基金对比表的本地工作区，主要产物是单文件 HTML 表格。

## 工作原则

- 终端是 Windows PowerShell。不要使用 Bash heredoc，例如 `python - <<'PY'`；需要内联 Python 时用 PowerShell here-string：`@' ... '@ | python -`。
- 默认使用 `nasdaq-fund-table` skill。动手前先读 `C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\SKILL.md`。
- 修改页面时改 `generate_nasdaq_fund_table.py`，不要直接改生成后的 `纳指基金支付宝对比表.html`，否则下次刷新数据会丢失改动。
- 每次改完生成脚本后，同步到 skill 脚本：
  `Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force`
- 当前目录是有效 Git 仓库，远端为 `https://github.com/Roverlo/nasdaq100-a-fund-pages.git`。每次代码更新后按用户规则提交并推送；推送直连失败时，用本机代理 `127.0.0.1:10808` 临时配置 Git 命令。
- 调试页面优先使用本地容器预览，不要再依赖 `file://`：`docker compose up -d` 后访问 `http://127.0.0.1:8765/`。Compose 使用本机已有的 `python:3.11-slim-bookworm` 镜像，通过 bind mount 暴露当前目录，`serve_static.py` 将根路径映射到生成 HTML 并禁用缓存，重新生成 HTML 后刷新浏览器即可看到更新。

## 核心文件

- `generate_nasdaq_fund_table.py`：唯一应编辑的生成脚本，含基金池、持仓、定投、评分、样式和交互。
- `纳指基金支付宝对比表.html`：生成产物，浏览器直接打开查看。
- `nasdaq_fund_snapshot.json`：本次抓取和计算快照，用于核对字段、评分、持仓和定投总额。
- `portfolio_tracking.json`：长期追踪记录，用于跨天、跨周、跨月保存持仓、市值、收益和收益率。生成脚本应按北京时间做“同日更新、跨日追加”：每天 3 次自动刷新只更新当天记录，第二天才追加新记录。页面应把它渲染成图表化追踪面板，而不只是表格。
- `data/nasdaq_funds.db`：SQLite 长期数据层，用于十年级别的结构化查询和学习；它由 `sync_sqlite_db.py` 从 `nasdaq_fund_snapshot.json` 与 `portfolio_tracking.json` 同步生成，包含 `execution_alerts` 表用于追溯申购状态/限额变化，不要手工改库后忘记回写源数据。`execution_alerts` 是历史事件表，不应为了匹配当前 72 小时页面提示而整表清空。
- `data/schema.sql`：SQLite 表和视图定义。改数据库结构时优先改这里，再让 `sync_sqlite_db.py` 应用；执行信息变化视图是 `v_recent_execution_alerts`。
- `data/examples.sql`：学习和排查用 SQL 示例。
- `sync_sqlite_db.py`：数据库同步脚本，完整刷新入口会自动调用。
- `direct_limits.json`：人工或 AI 从基金公司公告核实后的直销限额覆盖表。
- `direct_limit_candidates.json`：候选公告列表，不等于已核实直销限额。

## 当前用户口径

- 只保留纳指100相关 A / 人民币 A 类长期持有视角；非 A 类份额不要加入主表。
- 当前持有金额：南方 `016452=250`，汇添富 `018966=100`，建信 `539001=100`，万家 `019441=50`，摩根 `019172=20`，招商 `019547=20`，大成 `000834=10`，华安 `040046=10`，合计 `560`。
- 当前定投中金额按用户 2026-06-22 23:22/23:23 支付宝“我的定投”截图可见项：汇添富 `018966=100`，南方 `016452=50`，万家 `019441=50`，华安 `040046=10`，广发 `270042=10`，摩根 `019172=10`，招商 `019547=10`，大成 `000834=10`，宝盈 `019736=10`，华泰柏瑞 `019524=10`，合计 `270/期`；截图页显示进行中 `10` 条，这 10 条均已在截图中出现。
- 当前暂停定投金额按同一截图的“已暂停(2)”和旧明细保守保留：建信 `539001=100`，合计至少 `100/期`；另 1 条暂停项截图未展开，不能臆造。如果用户打开已暂停页截图，应按截图覆盖。`PAUSED_AUTO_INVEST_AMOUNTS` 只写已确认明细，不为了凑“已暂停(2)”虚构金额。
- 国泰纳斯达克100 `160213` 已加入基金池；当前持仓 `0`、定投 `0`，不加入持仓/定投明细，主表通过申购状态和限额列展示其限购/暂停申购状态。
- 定投频率当前记录为 `日定投`，下次扣款日当前记录为支付宝截图显示的 `2026-06-23`。这类信息来自用户截图或口述，变化后优先按用户最新说明更新。
- 定投计划金额是计划现金流，不自动计入当前持仓。`holding_total` 只能来自用户截图、手动确认、生成器持仓常量或未来已确认交易流水，不能把 `AUTO_INVEST_AMOUNTS` 直接加进去。
- 下次定投日要区分平台显示日期和预计基金业务日。脚本里的 `AUTO_INVEST_NEXT_DEBIT_BUSINESS_DATE` 应按中国内地公募基金业务日估算，排除周末和国务院办公厅公布的 2026 年法定节假日；QDII 还可能受海外市场休市、暂停申购、额度和平台扣款状态影响，最终以支付宝/基金公司订单页为准。

## 数据和评分

- `代销限额` 对应支付宝/蚂蚁基金等代销平台限额；`直销限额` 对应基金公司直销渠道限额。不要混成一列。
- “哪种数据最真实”的优先级：实际交易/定投页当前显示和下单结果 > 基金公司官网/公告/产品状态 > 官方披露镜像 PDF > 东方财富/天天基金等第三方接口 > 脚本回退值。申购状态、代销限额、下次扣款日、定投金额这种交易执行数据必须优先按支付宝/交易页事实；收益、规模、费率、跟踪误差可按公开接口自动刷新但要通过 `source_health` 校验。
- 如果用户截图或口述的支付宝/代销交易页限额与东方财富 `SGZT` 原文冲突，代销限额必须以实际交易入口为准，并写入 `generate_nasdaq_fund_table.py` 的 `AGENCY_LIMIT_OVERRIDES`；东方财富原文继续保存在 `subscription_status_raw`，不能再次覆盖交易入口校准值。当前万家 `019441` 代销限额按用户 2026-06-22 反馈校准为 `50`。
- `申购状态` 页面规范值只有 `允许申购` 和 `暂停申购`。东方财富 `SGZT` 原文如 `限大额(...)`、`开放申购` 应归一为 `允许申购`，原文继续保存在 `subscription_status_raw`；具体额度仍由 `代销限额` / `直销限额` 展示。
- `管理+托管` 只等于管理费率 + 托管费率。销售服务费单独展示，不并入主排序列。
- 梯队评级是当前基金池内相对排序，不是收益预测。当前权重为：近3年收益 35%、近1年收益 20%、跟踪误差 20%、管理+托管 15%、基金规模 6%、买入费率 2%、赎回灵活性 2%。
- `申购状态`、`代销限额`、`直销限额` 只作为筛选和交易执行信息，不参与梯队评级；不能因为暂停申购或限额低直接拉低基金质量评分。
- 每次完整刷新都要读取上一版 `nasdaq_fund_snapshot.json`，用本次抓取结果生成 `execution_alerts`。东方财富接口字段 `SGZT`、`daily_limit`、规模和收益属于每天 3 次自动刷新范围；直销限额只有在 `direct_limits.json` 或脚本回退值变化时才会触发对比，不要声称已自动核验基金公司公告。
- 执行信息提示保留 72 小时：限额上调在 `持仓 / 定投` 金额上显示绿色 `++`，限额下调显示红色 `--`；`暂停申购 -> 允许申购` 显示绿色恢复申购，`允许申购 -> 暂停申购` 显示红色暂停申购。用户手动/计划层面的 `暂停定投` 必须用黄色，和基金平台 `暂停申购` 的红色区分开。
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
- `nasdaq_fund_snapshot.json` 中 `auto_invest_plan.active_total` 应匹配页面定投中总额。
- `holding_plan.holding_total` 应匹配页面当前持有总额。
- `auto_invest_plan.cashflow_policy` 与 `holding_plan.cashflow_policy` 必须说明定投计划不自动计入持仓；`holding_plan.holding_total` 不应等于当前持仓加定投中总额。
- `auto_invest_plan.next_debit_business_date` 应与生成器按中国内地基金业务日计算出的日期一致。
- `nasdaq_fund_snapshot.json` 中 `source_health.checks` 应要求基础行情、费率赎回、跟踪误差均为全基金池成功；如果接口不可用导致回退值生成，应让验证失败，不要发布“假刷新”。
- 完整页的定投状态筛选必须只有 `定投中`、`暂停定投`、`候选`；公开首页不应重新带回定投状态筛选或持仓定投明细。
- 完整页和公开首页的申购状态筛选都必须只有 `允许申购`、`暂停申购`；如果未来 `prepare_github_pages.py` 重排公开页，也要继续保留这个二分类校验。
- `nasdaq_fund_snapshot.json` 每只基金的 `status` 必须落在 `定投中`、`暂停定投`、`候选`，`subscription_status` 必须落在 `允许申购`、`暂停申购`；原始接口文案只允许进入 `subscription_status_raw`。
- `portfolio_tracking.json` 应存在，最新记录日期应等于当前北京时间日期；最新记录的评级、评分、持仓金额、定投金额应与 `nasdaq_fund_snapshot.json` 一致；未知的市值、收益、收益率保持 `null` / `--`，不要用基金涨幅伪造个人收益。
- `data/nasdaq_funds.db` 应存在，`funds`、`fund_daily_snapshots`、`score_snapshots`、`portfolio_records`、`portfolio_positions`、`auto_invest_plans` 应与最新 JSON 口径一致；`transactions` 可以为空但表必须存在。
- 移动端样式改动后必须专项检查 `数据来源` tab：`source-table` 桌面端第一列有固定宽度，手机端卡片化时要覆盖 `td:first-child { width: auto; }`，并确认代码值如 `019441` 横向单行显示，不要被挤成竖排。

## SQLite 数据规则

- 当前数据库是长期查询和学习层，不替代生成器常量、主表快照和追踪 JSON 的源头地位。
- 个人真实收益字段仍按用户截图或手工输入维护；不要从基金阶段涨幅推导 `market_value`、`cost_basis`、`profit`、`return_rate`。
- `auto_invest_plans` 存的是计划层信息，包含原始 `next_debit_date` 和按中国内地基金业务日调整后的 `next_debit_business_date`。它不代表已成交，也不能直接改变 `portfolio_records.holding_total`。
- `portfolio_tracking.json` 的每条日记录也要保存当时的 `auto_invest_frequency`、`next_debit_date`、`next_debit_business_date` 和 `cashflow_policy`；SQLite 同步应优先使用该日记录里的值，不能用当前快照覆盖历史日期口径。
- `transactions` 只记录已确认事实流水，例如实际买入、卖出、分红、费用。未来如果接自动现金流，先生成待确认事件，确认扣款/成交后才写入 `transactions` 并更新持仓/成本口径。
- `sync_sqlite_db.py` 对 `generated_at`、`recorded_at` 做低噪声处理：同一天业务数据没变时，不应仅因时间戳导致 SQLite 文件变化，避免 GitHub Actions 每天 3 次无意义提交。
- 要学习数据库或排查数据时，优先用 `data/examples.sql` 和这些视图：`v_latest_fund_scores`、`v_portfolio_latest_positions`、`v_monthly_portfolio_summary`、`v_active_auto_invest_latest`。
- 如果以后要记录真实买卖流水，写入 `transactions`；但交易流水一旦作为事实数据使用，也要在 README 或专门记录文件中说明来源口径。

## 自动刷新

- GitHub Actions 工作流：`.github/workflows/refresh.yml`。
- 每天按北京时间 `08:45`、`16:45`、`23:15` 自动刷新，对应 UTC cron 为 `45 0,8 * * *` 和 `15 15 * * *`。
- 自动任务必须运行 `python refresh_all.py`，校验通过后再运行 `should_commit_refresh.py` 判断是否存在业务数据变化；只有纯时间戳变化时不提交，避免每天 3 次无意义 commit。
- 生成页内置发布版本轮询：GitHub Pages 页面每 5 分钟、窗口重新获得焦点、页面重新可见时检查当前 URL 是否已发布新版 HTML。只有检测到新版 `fund-page-generated-at` 大于当前页面时才自动 `location.reload()`，让标题更新时间和所有指标一起更新；不要做只改页面时间、不换业务数据的前端假刷新。
- 自动刷新产生的申购状态/限额变化要写入 `nasdaq_fund_snapshot.json.execution_alerts`，同步渲染到完整页和公开页，并同步进 SQLite `execution_alerts`；`validate_refresh_outputs.py` 应继续校验该结构，防止快照和页面提示脱节。
- `nasdaq_fund_snapshot.json.execution_alerts` 和页面角标只保留短窗口提醒；SQLite `execution_alerts` 要追加/幂等更新已发现事件，用 `detected_at + code + alert_type` 去重，保留历史追溯记录。
- 长期追踪的个人收益字段要保留：`market_value`、`cost_basis`、`profit`、`return_rate` 不应被自动刷新覆盖。

## UI 偏好

- 页面要紧凑、实用、可排序；不要加使用说明、解释性大段文字或无用 summary cards。
- 主表、持仓定投、长期追踪、梯队评级规则、数据来源作为 tab 展示。
- 主表列顺序按决策优先级排列：`排名`、`定投梯队`、`基金 / 代码`、`持仓 / 定投`、`近3年`、`近1年`、`跟踪误差`、`管理+托管`、`规模`、`买入费率`、`免赎回费门槛`、`申购状态`、`代销限额`、`直销限额`、`费率项目`、`卖出规则`、`日涨跌`、`定投状态`。默认排序必须落在 `定投梯队`，不要默认按基金名称或交易状态排序。
- `持仓定投` tab 只保留 `定投计划` 明细表和标题右侧总额，不放“当前持有”独立明细表、说明文字或 summary cards。当前持有金额仍通过标题总额、主表 `持仓 / 定投` 列、长期追踪和定投计划表的 `当前持有` 列展示。
- `持仓定投` tab 的 `定投计划` 明细表要在 `基金` 后展示 `评级` 列；评级必须复用主表同一套 `score_cards` / `investing_tier` / `investing_score`，不要做持仓专属评分。
- `持仓定投` tab 的 `定投计划` 表中，`评级`、`状态`、`金额`、`当前持有` 表头应支持点击排序，并显示和主表一致的排序箭头；排序只作用于定投计划表，不应改动主表排序。手机端会隐藏表头做卡片化布局，必须保留表上方的移动端排序按钮，不能让排序能力只在桌面可见。
- `持仓定投` tab 支持点击金额和定投状态做浏览器内手动编辑。金额用页面浮层编辑器，状态用自定义浮层菜单，不要用会撑开表格的原生 inline input/select。编辑结果写入 `localStorage` 的 `nasdaqFundPortfolioStateV1`，会即时刷新主表、定投计划表和标题总额，但不会自动写回 `generate_nasdaq_fund_table.py`。
- 主表和持仓编辑的定投状态只暴露三类：`定投中`、`暂停定投`、`候选`。`候选` 包含未定投基金和已持有但当前无定投计划的基金；不要再引入 `已持有`、`新增定投`、`定投中（含新增）` 作为筛选选项。
- 主表申购状态筛选只暴露两类：`允许申购`、`暂停申购`。不要再把 `限大额`、`开放申购` 做成筛选选项；限额信息已经有单独列。
- 如果用户确认浏览器内编辑结果要长期固化，必须把对应值同步回 `HOLDING_AMOUNTS`、`AUTO_INVEST_AMOUNTS`、`PAUSED_AUTO_INVEST_AMOUNTS`，再重新生成 HTML 和快照。
- `长期追踪` tab 布局参考 open-design 的紧凑 artifact/workbench 结构，以及 Ghostfolio、Wealthfolio、Portfolio Performance 的长期组合追踪视角：一行关键指标、资产轨迹图、收益轨迹图、持仓结构条、快照时间轴、基金明细，不放解释性大段文字。未知个人收益数据保持 `null` / `--`，不要用基金涨幅伪造个人收益。
- GitHub Pages 当前不再需要密钥：`docs/index.html` 是轻量公开页，`docs/portfolio.html` 是公开完整页。不要恢复 Staticrypt 或密码页，除非用户明确要求重新加密。
- 表格布局尽量基于容器自适应，不要为了单个屏幕写死宽度。
- 做移动端 review 时逐个 tab 检查真实可见交互，不要只看 DOM 里有没有桌面控件；如果表头被隐藏，对应排序/筛选入口要有手机端替代控件，并纳入 `validate_refresh_outputs.py`。
- 桌面表格列宽规则可能在移动端卡片化后继续作用到单元格；给辅助表新增固定列宽时，必须在移动端 media query 里确认是否需要覆盖，尤其是 `数据来源` 这种 label/value 卡片表。
- in-app browser 对 `file://` 页面可能禁止自动刷新或评估；遇到浏览器策略阻止时，用 HTML/JSON 结构检查验证，并提示用户手动刷新。
- in-app browser 对 `http://127.0.0.1:8765/` 可用于自动 reload、DOM 检查和截图验证；容器未启动时先启动 `nasdaq-fund-table` 服务。
- 如果浏览器评论/标注层开启，自动化点击可能命中 `codex-browser-sidebar-comments-root` 而不是页面按钮。遇到 tab/button 自动点击无效但控制台无报错时，先做 hit-test 或结构检查，必要时让用户关闭评论层后再验证，不要误判为页面脚本坏了。
