# GeBIZ 招投标自动化监测系统

本地部署的 GeBIZ (新加坡政府采购) 商机监测与跟进系统。

## 架构

- **后端**: FastAPI + SQLAlchemy + APScheduler + Playwright
- **存储**: SQLite（默认，可替换为 PostgreSQL）
- **前端**: 纯 HTML + 原生 JS（最小实现，零构建依赖）
- **通知**: 站内消息中心 / 邮件(SMTP) / Webhook

## 目录结构

```
backend/
  app/
    api/              # FastAPI 路由
    models/           # SQLAlchemy 模型
    services/         # 业务逻辑
    scrapers/         # GeBIZ 抓取器
    notifications/    # 通知渠道
    scheduler/        # 定时任务
    config.py
    database.py
    main.py
  requirements.txt
frontend/
  index.html          # 主工作台
  detail.html         # 详情页
  settings.html       # 提醒设置
  app.js
  styles.css
```

## 启动

```bash
cd backend
pip install -r requirements.txt
playwright install chromium
python -m app.main
```

访问 http://localhost:8000

## 配置

环境变量 (backend/.env)：
- `DATABASE_URL` (默认 sqlite:///./gebiz.db)
- `SCRAPE_CRON` (默认 `0 */4 * * *`, 每 4 小时)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`
- `ADMIN_ALERT_EMAILS` (逗号分隔)
- `USE_MOCK_SCRAPER=1` 使用 Mock 数据（开发时）

## 验收清单

见 PRD §8。
