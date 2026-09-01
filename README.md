# 重庆大学宿舍电费监控

定时登录重庆大学缴费平台，抓取宿舍电费余额和电表累计读数，并将每次抓取的原始数据保存为 CSV。账号、查询密码、房间及运行时间只从 `.env` 读取。

## 安装

```powershell
conda activate cqu-eb
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
CQU_ACCOUNT=你的学号
CQU_PASSWORD=你的查询密码
CQU_ROOM=D3167
CQU_BUILDING=兰园3栋
SCHEDULE_TIMES=00:00,12:00
TIMEZONE=Asia/Shanghai
```

`.env` 已加入 `.gitignore`，请勿提交或分享该文件。`CQU_BUILDING` 通常可以留空；若不同楼栋存在同名房间，则填写页面显示的楼栋名称。

## 运行

单次抓取：

```powershell
conda activate cqu-eb
python -m cqu_electricity once
```

在当前终端持续定时运行：

```powershell
python -m cqu_electricity daemon
```

根据 `history.csv` 生成最近 14 个自然日的用电图表：

```powershell
python -m cqu_electricity plot
```

默认输出为 `history.png`。也可以指定输出位置：

```powershell
python -m cqu_electricity plot --output charts/electricity.png
```

Windows 下可用任务计划程序在登录或开机时执行以上 `daemon` 命令；Linux 可交给 systemd、supervisor 或 Docker 管理。程序自身不静默派生进程，日志与停止行为更容易管理。

## CSV 输出

每次抓取都会向项目根目录的 `history.csv` 追加一行原始数据，字段包括抓取时间、房间、楼栋、余额、电表累计读数、剩余电补助和电表地址。程序不计算增量、每日汇总或估算费用。可通过 `DATA_DIR` 改变保存目录。

制图时才会按日期选取当天最后一次记录，用当天与前一天的累计电表读数之差得到每日用电量。柱状图表示每日用电量，折线图表示当天最后一次余额；缺少采样的日期会留空，不会被错误地当作零用电。

## 常见问题

- 登录页验证码由本机 `ddddocr` 识别，识别失败会自动换图重试，不会上传图片或凭据。
- 学校电费子系统会返回校内 `10.x` 地址，程序会自动改写为公开的 `card.cqu.edu.cn:8080/charge` 反向代理路径。
- 若学校修改页面或接口，程序会明确报告缺少的字段，不会写入虚假数据。
