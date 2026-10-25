# Chicago 二手车搜索

用 MarketCheck API 搜索 dealer 在售二手车，按标价排序并导出 CSV。默认搜索 60601 周边 50 英里内、$18,000 以内、90,000 英里以内的 Toyota Corolla。它只是初筛，低价不代表车况好或最终落地价低。

## 使用

1. 在 https://developers.marketcheck.com/ 注册并获取 API key，确认套餐额度和支持的搜索范围。
2. 在此文件夹打开 PowerShell，设置当前窗口的环境变量并运行：

```powershell
$env:MARKETCHECK_API_KEY = "你的API_KEY"
.\.venv\Scripts\python.exe .\search_cars.py
```

结果保存在 `chicago_cars.csv`，可以用 Excel 打开。环境变量只在当前 PowerShell 窗口有效，不要把 key 提交到 Git。

自定义条件：

```powershell
.\.venv\Scripts\python.exe .\search_cars.py --zip 60601 --radius 50 --make Honda --model Civic --max-price 20000 --max-miles 80000 --pages 5 --output civic.csv
```

运行 ` .\.venv\Scripts\python.exe .\search_cars.py --help` 查看选项。每页最多请求 50 条，默认最多 5 页；API 返回的总数大于请求上限时，结果可能不完整。确认车源是否仍在售、事故和 title 记录，以及包含费用和税的落地价。

项目环境使用本机 Codex 自带 Python 3.12 创建，脚本仅依赖 Python 标准库。该环境依赖 Codex 的 Python 安装位置；若之后不可用，可安装 Python 3.12 或更新版本，然后在此文件夹用 `py -m venv .venv` 重建环境。
