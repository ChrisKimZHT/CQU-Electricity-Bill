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

抓取最新数据、生成 14 天图表并立即发送邮件：

```powershell
python -m cqu_electricity email
```

邮件的 HTML 正文包含当前余额、电表累计读数等信息，`history.png` 会转换为 Base64 Data URI 内嵌。若希望 `once` 和 `daemon` 每次成功抓取后自动发送，将 `.env` 中的 `EMAIL_ENABLED` 改为 `true`。

SMTP SSL（常见于 465 端口）配置示例：

```dotenv
EMAIL_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=your_email@example.com
SMTP_PASSWORD=你的SMTP授权码
SMTP_FROM=your_email@example.com
SMTP_TO=recipient@example.com
SMTP_USE_SSL=true
SMTP_STARTTLS=false
```

SMTP STARTTLS（常见于 587 端口）需要设置 `SMTP_USE_SSL=false`、`SMTP_STARTTLS=true`。多个收件人使用英文逗号分隔。部分邮箱要求使用单独的 SMTP 授权码，而不是邮箱登录密码。

Windows 下可用任务计划程序在登录或开机时执行以上 `daemon` 命令；Linux 可交给 systemd、supervisor 或 Docker 管理。程序自身不静默派生进程，日志与停止行为更容易管理。

## Docker

构建镜像：

```powershell
docker build -t cqu-electricity-bill .
```

默认启动命令为 `daemon`。账号、房间和定时配置通过 `-e` 手动传入；`DATA_DIR` 已由容器入口固定为 `/data`，挂载该目录即可持久化 `history.csv` 与 `history.png`：

```powershell
docker run -d `
  --name cqu-electricity-bill `
  --restart unless-stopped `
  -e CQU_ACCOUNT="你的学号" `
  -e CQU_PASSWORD="你的查询密码" `
  -e CQU_ROOM="D3617" `
  -e CQU_BUILDING="兰园3栋" `
  -e SCHEDULE_TIMES="00:00,12:00" `
  -e TIMEZONE="Asia/Shanghai" `
  -e LOG_LEVEL="INFO" `
  -v "${PWD}/data:/data" `
  cqu-electricity-bill
```

需要自动发送邮件时，继续添加 SMTP 环境变量：

```powershell
  -e EMAIL_ENABLED="true" `
  -e SMTP_HOST="smtp.example.com" `
  -e SMTP_PORT="465" `
  -e SMTP_USERNAME="your_email@example.com" `
  -e SMTP_PASSWORD="你的SMTP授权码" `
  -e SMTP_FROM="your_email@example.com" `
  -e SMTP_TO="recipient@example.com" `
  -e SMTP_USE_SSL="true" `
  -e SMTP_STARTTLS="false" `
```

查看日志：

```powershell
docker logs -f cqu-electricity-bill
```

也可以把上述相同的 `-e` 和 `-v` 参数用于单次抓取、制图或邮件发送，并在镜像名称后指定命令：

```powershell
docker run --rm [相同的 -e 参数] -v "${PWD}/data:/data" cqu-electricity-bill once
docker run --rm [相同的 -e 参数] -v "${PWD}/data:/data" cqu-electricity-bill plot
docker run --rm [相同的 -e 参数] -v "${PWD}/data:/data" cqu-electricity-bill email
```

镜像内安装了 Noto CJK 中文字体，Docker 生成图表时不会依赖宿主机的微软雅黑。

## CSV 输出

每次抓取都会向项目根目录的 `history.csv` 追加一行原始数据，字段包括抓取时间、房间、楼栋、余额、电表累计读数、剩余电补助和电表地址。程序不计算增量、每日汇总或估算费用。可通过 `DATA_DIR` 改变保存目录。

制图时才会按日期选取当天最后一次记录，用当天与前一天的累计电表读数之差得到每日用电量。柱状图表示每日用电量，折线图表示当天最后一次余额；缺少采样的日期会留空，不会被错误地当作零用电。

## 常见问题

- 登录页验证码由本机 `ddddocr` 识别，识别失败会自动换图重试，不会上传图片或凭据。
- 学校电费子系统会返回校内 `10.x` 地址，程序会自动改写为公开的 `card.cqu.edu.cn:8080/charge` 反向代理路径。
- 若学校修改页面或接口，程序会明确报告缺少的字段，不会写入虚假数据。
