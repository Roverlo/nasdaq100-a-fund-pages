# Codex 维护规则

本目录是纳指100 QDII A 类基金对比表的本地工作区，主要产物是单文件 HTML 表格。

## 工作原则

- 终端是 Windows PowerShell。不要使用 Bash heredoc，例如 `python - <<'PY'`；需要内联 Python 时用 PowerShell here-string：`@' ... '@ | python -`。
- 默认使用 `nasdaq-fund-table` skill。动手前先读 `C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\SKILL.md`。
- 修改页面时改 `generate_nasdaq_fund_table.py`，不要直接改生成后的 `纳指基金支付宝对比表.html`，否则下次刷新数据会丢失改动。
- 每次改完生成脚本后，同步到 skill 脚本：
  `Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force`
- 当前目录有 `.git` 文件夹，但 `git rev-parse --is-inside-work-tree` 报 `not a git repository`。在修复或重新初始化 Git 之前，不要声称已提交或推送。
- 调试页面优先使用本地容器预览，不要再依赖 `file://`：`docker compose up -d` 后访问 `http://127.0.0.1:8765/`。Compose 使用本机已有的 `python:3.11-slim-bookworm` 镜像，通过 bind mount 暴露当前目录，`serve_static.py` 将根路径映射到生成 HTML 并禁用缓存，重新生成 HTML 后刷新浏览器即可看到更新。

## 核心文件

- `generate_nasdaq_fund_table.py`：唯一应编辑的生成脚本，含基金池、持仓、定投、评分、样式和交互。
- `纳指基金支付宝对比表.html`：生成产物，浏览器直接打开查看。
- `nasdaq_fund_snapshot.json`：本次抓取和计算快照，用于核对字段、评分、持仓和定投总额。
- `portfolio_tracking.json`：长期追踪记录，用于跨天、跨周、跨月保存持仓、市值、收益和收益率。生成脚本只在文件不存在或无记录时写入初始基线，不要每次刷新自动追加重复记录。页面应把它渲染成图表化追踪面板，而不只是表格。
- `direct_limits.json`：人工或 AI 从基金公司公告核实后的直销限额覆盖表。
- `direct_limit_candidates.json`：候选公告列表，不等于已核实直销限额。

## 当前用户口径

- 只保留纳指100相关 A / 人民币 A 类长期持有视角；非 A 类份额不要加入主表。
- 当前持有金额：南方 `016452=250`，汇添富 `018966=100`，建信 `539001=100`，万家 `019441=50`，摩根 `019172=20`，招商 `019547=20`，大成 `000834=10`，华安 `040046=10`，合计 `560`。
- 当前定投中金额：万家 `019441=200`，南方 `016452=50`，华安 `040046=10`，广发 `270042=10`，摩根 `019172=10`，招商 `019547=10`，华泰柏瑞 `019524=10`，合计 `300/期`。
- 当前暂停定投金额：汇添富 `018966=100`，建信 `539001=100`，大成 `000834=10`，宝盈 `019736=10`，合计 `220/期`。
- 定投频率当前记录为 `日定投`，下次扣款日当前记录为 `2026-06-22`。这类信息来自用户截图或口述，变化后优先按用户最新说明更新。

## 数据和评分

- `代销限额` 对应支付宝/蚂蚁基金等代销平台限额；`直销限额` 对应基金公司直销渠道限额。不要混成一列。
- `管理+托管` 只等于管理费率 + 托管费率。销售服务费单独展示，不并入主排序列。
- 梯队评级是当前基金池内相对排序，不是收益预测。当前权重为：近3年收益 35%、近1年收益 20%、跟踪误差 20%、管理+托管 15%、基金规模 6%、买入费率 2%、赎回灵活性 2%。
- `申购状态`、`代销限额`、`直销限额` 只作为筛选和交易执行信息，不参与梯队评级；不能因为暂停申购或限额低直接拉低基金质量评分。
- 直销限额变化频繁，重要比较前要重新查基金公司公告或官方披露。

## 验证流程

改动后至少执行：

```powershell
python -m py_compile "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py"
python "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" --output-dir "C:\ALL_in_H\纳指记录"
Copy-Item -LiteralPath "C:\ALL_in_H\纳指记录\generate_nasdaq_fund_table.py" -Destination "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py" -Force
python -m py_compile "C:\Users\胡文雨\.codex\skills\nasdaq-fund-table\scripts\generate_nasdaq_fund_table.py"
```

再做结构检查：

- `#main-table` 表头列数应等于每行单元格数。
- 当前主表应为 `18` 列、`16` 行，除非基金池有意变更。
- `nasdaq_fund_snapshot.json` 中 `auto_invest_plan.active_total` 应匹配页面定投中总额。
- `holding_plan.holding_total` 应匹配页面当前持有总额。
- `portfolio_tracking.json` 应存在，且 `长期追踪` tab 能读取最近记录；未知的市值、收益、收益率保持 `null` / `--`，不要用基金涨幅伪造个人收益。

## UI 偏好

- 页面要紧凑、实用、可排序；不要加使用说明、解释性大段文字或无用 summary cards。
- 主表、持仓定投、长期追踪、梯队评级规则、数据来源作为 tab 展示。
- 主表列顺序按决策优先级排列：`排名`、`定投梯队`、`基金 / 代码`、`持仓 / 定投`、`近3年`、`近1年`、`跟踪误差`、`管理+托管`、`规模`、`买入费率`、`免赎回费门槛`、`申购状态`、`代销限额`、`直销限额`、`费率项目`、`卖出规则`、`日涨跌`、`定投状态`。默认排序必须落在 `定投梯队`，不要默认按基金名称或交易状态排序。
- `持仓定投` tab 只保留明细表和标题右侧总额，不放说明文字。
- `持仓定投` tab 的“当前持有”和“定投计划”明细表都要在 `基金` 后展示 `评级` 列；评级必须复用主表同一套 `score_cards` / `investing_tier` / `investing_score`，不要做持仓专属评分。
- `持仓定投` tab 支持点击金额和定投状态做浏览器内手动编辑。金额用页面浮层编辑器，状态用自定义浮层菜单，不要用会撑开表格的原生 inline input/select。编辑结果写入 `localStorage` 的 `nasdaqFundPortfolioStateV1`，会即时刷新主表、两张明细表和标题总额，但不会自动写回 `generate_nasdaq_fund_table.py`。
- 如果用户确认浏览器内编辑结果要长期固化，必须把对应值同步回 `HOLDING_AMOUNTS`、`AUTO_INVEST_AMOUNTS`、`PAUSED_AUTO_INVEST_AMOUNTS`，再重新生成 HTML 和快照。
- `长期追踪` tab 布局参考 open-design 的紧凑 artifact/workbench 结构，以及 Ghostfolio、Wealthfolio、Portfolio Performance 的长期组合追踪视角：一行关键指标、资产轨迹图、收益轨迹图、持仓结构条、快照时间轴、基金明细，不放解释性大段文字。未知个人收益数据保持 `null` / `--`，不要用基金涨幅伪造个人收益。
- 表格布局尽量基于容器自适应，不要为了单个屏幕写死宽度。
- in-app browser 对 `file://` 页面可能禁止自动刷新或评估；遇到浏览器策略阻止时，用 HTML/JSON 结构检查验证，并提示用户手动刷新。
- in-app browser 对 `http://127.0.0.1:8765/` 可用于自动 reload、DOM 检查和截图验证；容器未启动时先启动 `nasdaq-fund-table` 服务。
- 如果浏览器评论/标注层开启，自动化点击可能命中 `codex-browser-sidebar-comments-root` 而不是页面按钮。遇到 tab/button 自动点击无效但控制台无报错时，先做 hit-test 或结构检查，必要时让用户关闭评论层后再验证，不要误判为页面脚本坏了。
