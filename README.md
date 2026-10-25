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
