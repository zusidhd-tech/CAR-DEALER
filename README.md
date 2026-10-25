# 本地网页界面

在项目文件夹的 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe .\app.py
```

然后在浏览器打开 http://127.0.0.1:8000 。界面会合并 Auto.dev 与免费的 CLCAuto 数据。填写 ZIP、半径、城市、品牌、车型、预算和里程后点击搜索；结果卡片显示数据来源、标价、市场比较、降价，以及可点击的价格历史。按 Ctrl+C 停止服务。端口被占用时可用 `--port 8001`，并打开对应端口。

每次成功搜索都会把目标车价格保存在项目目录的 `car_history.sqlite3`。首次记录没有此前的降价；只有再次搜索到同一车源时才能检测变化。页面不会后台定时搜索，也不会主动推送通知。

## 更大的实时车源：Auto.dev

Auto.dev 免费套餐无需信用卡，每月提供 1,000 次调用，免费层每页最多返回 20 辆。登录 Auto.dev 后在 API Keys 页面创建 key，并存入 Windows 用户环境：

```powershell
[Environment]::SetEnvironmentVariable("AUTODEV_API_KEY", "你的API_KEY", "User")
```

重新打开 PowerShell 后启动网页。应用也会读取 Windows 用户环境中的 key，因此通常无需重启 Codex。key 只在 Python 服务端使用，不会发送到浏览器或写入 Git。Auto.dev 认证失败或额度用尽时，页面会显示原因并继续使用 CLCAuto 结果。

界面中的“搜索页数”控制 Auto.dev 请求量：免费层每页 20 辆，默认 5 页即最多获取 100 辆，每次搜索最多消耗 5 次调用。返回总数大于已获取数量时，结果会标记为样本不完整。

# 免费搜索：CLCAuto

`search_clcauto.py` 使用 [CLCAuto 公开只读接口](https://www.clcauto.com/en/developers)，无需 API key 或信用卡。它是免费的商业平台接口，并非开源数据库。接口支持按城市文字筛选，不支持按 ZIP 和半径筛选；芝加哥郊区可能不包含在结果中。只保留 dealer、美元和英里车源，匿名接口没有完整 VIN，因此使用平台车源 ID 跟踪价格，同一车辆重新刊登后可能无法关联。数据覆盖有限，不能代表整个市场。

```powershell
.\.venv\Scripts\python.exe .\search_clcauto.py
.\.venv\Scripts\python.exe .\search_clcauto.py --make Toyota --model Corolla --max-price 20000 --max-miles 90000 --location Chicago --pages 5
```

默认搜索 Chicago，价格不超过 $18,000、里程不超过 90,000 英里的 dealer 车辆。`--pages` 默认最多 5 页，每页 100 条；若结果超过上限，市场比较标记为不完整。结果存入 `chicago_clcauto.csv`，历史存入 `car_history.sqlite3`。每次运行比较同一车源上次记录，终端和 CSV 会显示降价。查看历史时使用 `search_cars.py --history CLC:车源ID`。公开接口限制每 IP 每分钟 20 次，频繁运行可能被限流。

市场中位数使用同一地点、车型和配置，相差不超过一年和 15,000 英里的至少 5 辆车。样本较少时不会估价；它是本平台在售标价的粗略比较，不是成交价或完整市场估值。首次搜索没有以前的历史。具体选项见 `search_clcauto.py --help`。

---

# Chicago 二手车搜索

通过 [MarketCheck](https://docs.marketcheck.com/docs/api/cars/inventory/inventory-search) 搜索附近 dealer 的在售二手车，导出 CSV、记录价格历史、提示降价，并估算相似车辆的标价中位数。

## 功能

- 按 ZIP code、半径、品牌、车型、最高标价和最大里程搜索，按 VIN 去重并按标价排序。
- 将每次搜索到的目标车价格存入本地 SQLite 数据库。下次搜索同一 VIN 时，终端和 CSV 显示相对上次观察的降价金额和百分比；首次出现不会显示降价。
- 单独搜索同品牌、车型和地区的市场样本，不套用目标搜索的价格或里程上限。比较相同配置、年份相差不超过 1 年、里程相差不超过 15,000 英里的其他车辆；至少有 5 辆时计算标价中位数及目标车与中位数的差额。
- 查看指定 VIN 的本地观察记录。没有 VIN 的车可以出现在 CSV，但不会记录历史。

## 准备和运行

需要 Python 3.12 或更新版本以及 [MarketCheck API key](https://developers.marketcheck.com/)。确认账户套餐额度和搜索范围。脚本使用标准库，无需第三方包。首次安装 Python 后可在项目目录运行 `py -m venv .venv`；本机已有项目环境可跳过。

在 PowerShell 中运行：

```powershell
$env:MARKETCHECK_API_KEY = "你的API_KEY"
.\.venv\Scripts\python.exe .\search_cars.py
```

默认搜索 Chicago `60601` 周边 50 英里内标价 $1,000–$18,000、里程不超过 90,000 英里的 Toyota Corolla。结果写入 `chicago_cars.csv`，价格历史保存在 `car_history.sqlite3`。每次运行会覆盖同名 CSV，数据库会保留每次观察。环境变量只在当前 PowerShell 窗口有效；不要提交 API key。

```powershell
.\.venv\Scripts\python.exe .\search_cars.py --zip 60601 --radius 50 --make Honda --model Civic --max-price 20000 --max-miles 80000 --pages 5 --output civic.csv
.\.venv\Scripts\python.exe .\search_cars.py --history 车辆VIN
```

`--history` 不需要 API key。终端显示的记录时间为 UTC。价格历史只从开始使用本脚本时积累；定期运行才能发现变化。提醒在运行时显示，不会自动发送邮件或手机通知。同一 VIN 的 dealer 发生变化时，降价也可能来自不同 dealer 的标价。

## 参数

| 参数 | 含义 | 默认值 |
| --- | --- | --- |
| `--zip` | 搜索中心 ZIP code | `60601` |
| `--radius` | 搜索半径，英里 | `50` |
| `--make` / `--model` | 品牌 / 车型 | `Toyota` / `Corolla` |
| `--max-price` | 最高标价，美元，至少 1,000 | `18000` |
| `--max-miles` | 最大里程，英里 | `90000` |
| `--pages` | 目标搜索和市场搜索各自的最多页数，每页 50 条 | `5` |
| `--output` | CSV 输出路径；同名文件会覆盖 | `chicago_cars.csv` |
| `--database` | SQLite 历史数据库路径 | `car_history.sqlite3` |
| `--history VIN` | 查看本地指定 VIN 的价格记录 | 无 |

有目标车时通常执行两组搜索，因此最多消耗 `2 × pages` 次 API 请求；实际调用量受结果数量影响。搜索范围、页数和返回数据受 API 套餐限制。`--help` 显示全部选项。

## 如何看比较结果

CSV 的 `market_median`、`comparable_count`、`market_difference` 和 `market_difference_percent` 显示参考中位数、可比数量以及当前标价减去中位数的差值（负数表示低于中位数）。`market_status` 含义：

- `below_median`、`at_median`、`above_median`：与获取到的完整样本中位数比较。
- `insufficient_comparables`：可比车少于 5 辆，或年份、配置、里程等信息不足，无法估价。
- `sample_incomplete`：市场搜索达到页数上限；数值仅基于已获取样本，可能有偏差。可在套餐允许时增加 `--pages`。

参考价是附近在售车的标价中位数，并非成交价或专业估值，不能反映事故、title、维修、配置细节、税费和 dealer 附加费用。实际购买前应确认车辆是否仍在售、检查车况，并向 dealer 索取书面落地价。
