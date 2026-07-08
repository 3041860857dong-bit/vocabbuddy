# VocabBuddy 云服务器部署指南

> 适用场景：把 VocabBuddy（FastAPI + MySQL + 同源前端）部署到云服务器（如腾讯云 CVM），
> 让任何人都能通过浏览器访问。
>
> 本文假设你已有一台云服务器（Ubuntu 22.04/24.04 或 TencentOS）和（可选）一个域名。

---

## 一、部署前已经帮你改好的代码（无需再动）

| 改动 | 原因 |
|------|------|
| 前端移入 `static/`，后端只托管 `static/` 目录 | **原代码 `StaticFiles(directory=项目根)` 会把 `.env`（含数据库密码/JWT 密钥/大模型 Key）、`backend/` 源码、`deliverables/` 全部公开下载**。这是最严重的安全隐患，已修复。 |
| `VOCABBUDDY_ENV=production` 时关闭 `/docs`、`/redoc`、`/openapi.json` | 避免在生产环境暴露接口结构。 |
| CORS 来源改为 `VOCABBUDDY_CORS_ORIGINS` 环境变量 | 默认仍是本地开发地址；上线时填你的域名。 |
| `requirements.txt` 锁定版本 | 保证云端依赖可复现。 |
| 新增 `.gitignore` | 防止 `.env` 等密钥被误提交。 |

> 前端所有 API 请求本来就用同源相对路径（`/api/...`），并在 FastAPI 同源托管，
> 因此**前端无需改任何接口地址**即可上云。

---

## 二、环境变量清单

全部通过环境变量注入（`.env` 文件或容器/系统环境变量），已在 `backend/config.py` 中读取。

| 变量 | 说明 | 是否必填 |
|------|------|----------|
| `VOCABBUDDY_DB_URL` | SQLAlchemy 连接串，如 `mysql+pymysql://vocabbuddy:密码@主机:3306/vocabbuddy` | 是 |
| `VOCABBUDDY_JWT_SECRET` | JWT 签名密钥，**生产必须随机长字符串** | 是 |
| `VOCABBUDDY_JWT_EXPIRE_MINUTES` | token 有效期（分钟），默认 60，建议 1440 | 否 |
| `VOCABBUDDY_ENV` | `development`/`production`；生产设 `production` | 建议 |
| `VOCABBUDDY_CORS_ORIGINS` | 跨域来源，逗号分隔；同源部署可留空 | 否 |
| `VOCABBUDDY_LLM_API_KEY` | 大模型 Key（混淆项/同义词）；留空自动降级兜底 | 否 |
| `VOCABBUDDY_LLM_BASE_URL` | 大模型 base url，默认 DeepSeek | 否 |
| `VOCABBUDDY_LLM_MODEL` | 模型名，默认 `deepseek-chat` | 否 |

生成随机 JWT 密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 二-B、入门档实操清单（你已选定的方案，照抄即可）

你已拍板：**Docker Compose 部署 + 腾讯云 TencentDB（托管）+ 暂用公网 IP/HTTP + 入门档**（≈¥330/月，年付再省约 15%）。
下面是照抄步骤，所有命令在 CVM 上以具有 sudo 权限的普通用户执行。

### 第 1 步：买 CVM（控制台点选）
- 进入「云服务器 CVM」→ 新建实例
- 地域：广州 / 上海 / 北京 任选（同价）
- 机型：**标准型 SA5，2 核 4 GB**（AMD，比同规格 Intel 便宜约 10–20%）
- 镜像：**Ubuntu 22.04 LTS**（64 位）
- 系统盘：通用型 SSD，**50 GB**
- 公网带宽：**按带宽包 2 Mbps**（流量极低也可选按流量，更省）
- 购买方式：先选**按量计费**跑通验证 1–2 周，确认规格合适后转**包年包月（年付）**最省
- 安全组：只放通 **22（SSH）** 与 **80（HTTP）**；SSH 建议改非 22 端口 + 密钥登录 + Fail2ban
- 记下分配到的**公网 IP**

> 最省备选：**轻量应用服务器 Lighthouse 2核4G 套餐**（含 4–6Mbps 带宽 + 60–80GB SSD，¥80–120/月），单应用足够；但后续做复杂组网不如 CVM 灵活。

### 第 2 步：买 TencentDB for MySQL（控制台点选）
- 进入「云数据库 TencentDB」→ MySQL → 新建
- 版本：**MySQL 8.0**
- 架构：**双节点（高可用版）**，规格 **1 核 2 GB / 50 GB SSD**（预算极紧可改单节点基础版，但无自动故障切换）
- 地域/可用区：与 CVM **同一地域、同一私有网络（VPC）**
- 字符集：utf8mb4
- 新建账号 `vocabbuddy` 与库 `vocabbuddy`
- 记下控制台给出的 **内网地址**（形如 `cdb-xxxx.bj.tencentcdb.com` 或内网 IP）和端口 3306
- **白名单/安全组**：把第 1 步 CVM 的**内网 IP** 加进去（不要长期开 `0.0.0.0/0`）

### 第 3 步：登录 CVM，一键初始化
本地把项目传上去：
```bash
scp -r /本地路径/vocabbuddy 你的用户名@公网IP:~/vocabbuddy
```
在 CVM 上：
```bash
cd ~/vocabbuddy
chmod +x deploy/first-boot.sh
./deploy/first-boot.sh        # 首次会生成 .env 并提示填写，填完再跑一次
```
脚本自动完成：装 Docker → 生成 `.env` → `docker compose up -d --build` → 等 `/health` → 导词库 → 验证。

### 第 4 步：填 `.env`（关键）
编辑 `~/vocabbuddy/.env`，至少改这两项：
```bash
VOCABBUDDY_DB_URL=mysql+pymysql://vocabbuddy:你的库密码@TencentDB内网地址:3306/vocabbuddy
VOCABBUDDY_JWT_SECRET=把这里换成随机长字符串   # 生成：python3 -c "import secrets;print(secrets.token_urlsafe(48))"
```
保存后重新跑一次 `./deploy/first-boot.sh`。

### 第 5 步：验证
浏览器打开 `http://公网IP:8000` 应看到 VocabBuddy；`curl http://公网IP:8000/health` 应返回 `{"status":"ok"}`。

### ⚠️ 上线前提醒
- 当前走 **HTTP 明文**，账号/学习进度可被窃听。**尽快上 HTTPS**（见方式 B 的 Nginx + certbot；或后续再加）。
- 应用端口 8000 随 CVM 安全组只对你开放；想完全不暴露，可加 Nginx 只开 80/443 反代（方式 B）。
- 开启 TencentDB 自动备份（默认保留 7 天，建议延长），并对词库/配置定期快照。

---

## 三、方式 A：腾讯云 CVM + Docker（推荐，最简单）

### 1. 在 CVM 上准备
```bash
# 安装 Docker 与 docker compose 插件（Ubuntu 示例）
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER   # 重新登录后生效
```

### 2. 上传代码
把整个项目目录传到 CVM（如 `/opt/vocabbuddy`），然后进入该目录。

### 3. 准备 `.env`
复制 `deploy/.env.server.example` 为 `.env` 并填入真实值：
```bash
cp deploy/.env.server.example .env
nano .env
```
注意：当前 `deploy/docker-compose.yml` 是**仅应用**编排，数据库走外部 TencentDB（见「入门档实操清单」与第五节）。
因此 `.env` 只需填 `VOCABBUDDY_DB_URL` 等应用变量，无需 MySQL 容器相关变量。
若想改用容器自带 MySQL，改用 `deploy/docker-compose.db.yml`。

### 4. 构建并启动
```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
```

### 5. 导入词库（一次性）
词库 JSON 已在 `backend/word_data/`，首次启动后执行：
```bash
docker compose -f deploy/docker-compose.yml exec app \
  python -m backend.import_words
```

### 6. 验证
```bash
curl http://localhost:8000/health      # 应返回 {"status":"ok"}
curl http://localhost:8000/            # 应返回前端 HTML
```

> 数据库为外部 TencentDB（托管），连接串在 `.env` 的 `VOCABBUDDY_DB_URL`。若要用容器自带 MySQL，改用 `deploy/docker-compose.db.yml`。

---

## 四、方式 B：CVM 直接部署（systemd + Nginx + 免费 HTTPS）

适合不想用 Docker、希望用系统服务管理进程的场景。

### 1. 安装运行环境
```bash
sudo apt update
sudo apt install -y python3.13 python3.12-venv mysql-server nginx
```

### 2. 部署代码与虚拟环境
```bash
sudo mkdir -p /opt/vocabbuddy
sudo cp -r /你本地项目/* /opt/vocabbuddy/
sudo python3.13 -m venv /opt/vocabbuddy/venv
sudo /opt/vocabbuddy/venv/bin/pip install -r /opt/vocabbuddy/backend/requirements.txt
sudo useradd -m vocabbuddy
sudo chown -R vocabbuddy:vocabbuddy /opt/vocabbuddy
```

### 3. 数据库（本机 MySQL 8）
```sql
CREATE DATABASE vocabbuddy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'vocabbuddy'@'localhost' IDENTIFIED BY '你的密码';
GRANT ALL PRIVILEGES ON vocabbuddy.* TO 'vocabbuddy'@'localhost';
FLUSH PRIVILEGES;
```
> 也可直接用现成的云数据库（见第五节），把 `VOCABBUDDY_DB_URL` 指向内网地址即可。

### 4. 配置 `.env` 并设为仅 owner 可读
```bash
sudo cp /opt/vocabbuddy/deploy/.env.server.example /opt/vocabbuddy/.env
sudo nano /opt/vocabbuddy/.env
sudo chmod 600 /opt/vocabbuddy/.env
```

### 5. 注册 systemd 服务
```bash
sudo cp /opt/vocabbuddy/deploy/vocabbuddy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vocabbuddy
sudo systemctl status vocabbuddy
```

### 6. 配置 Nginx + HTTPS（certbot 免费证书）
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo cp /opt/vocabbuddy/deploy/nginx.conf /etc/nginx/conf.d/vocabbuddy.conf
# 把里面的 your-domain.example.com 改成你的域名，并确保域名已解析到该 CVM
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d 你的域名        # 自动签发并配置证书，续期也自动
```

### 7. 导入词库
```bash
sudo -u vocabbuddy /opt/vocabbuddy/venv/bin/python -m backend.import_words
```
（在 `/opt/vocabbuddy` 目录下执行；`import_words` 依赖 `backend` 包，已通过包结构支持。）

---

## 五、数据库选择：自建 vs 云数据库（TencentDB）

- **新手 / 小流量**：方式 B 的本机 MySQL，或 `deploy/docker-compose.db.yml` 的容器 MySQL 即可；若图省心直接选下方 TencentDB。
- **省心 / 高可用 / 自动备份**：直接用**腾讯云 TencentDB for MySQL**。
  1. 控制台创建实例，字符集选 `utf8mb4`。
  2. 新建账号 `vocabbuddy` 与库 `vocabbuddy`。
  3. 把 `VOCABBUDDY_DB_URL` 指向实例**内网地址**（`mysql+pymysql://vocabbuddy:密码@内网IP:3306/vocabbuddy`）。
  4. CVM 与 TencentDB 放在**同一地域/私有网络**，走内网免费且低延迟。
- 表的 `en` 列已强制 `utf8mb4_bin` 列级排序规则（避免 `resume`/`resumé` 冲突），
  只要库是 `utf8mb4` 就无需额外处理。

---

## 六、上线安全自查清单

- [ ] `.env` 未被挂载到项目根被 `StaticFiles` 暴露（已修复为只挂 `static/`）。
- [ ] `VOCABBUDDY_JWT_SECRET` 已替换为随机长字符串。
- [ ] `VOCABBUDDY_ENV=production`（关闭了 `/docs`）。
- [ ] 数据库密码非弱口令；云数据库走内网。
- [ ] 已启用 HTTPS（certbot），前端 localStorage 中的 JWT 不再明文裸奔。
- [ ] `.env` 文件权限 `600`，且被 `.gitignore` 忽略。
- [ ] 服务器只开放必要端口（80/443 + 运维 22），数据库端口不对外。
- [ ] 已配置开机自启（systemd `enable` 或 compose `restart: unless-stopped`）。

---

## 七、验证与排错

```bash
# 健康检查
curl https://你的域名/health

# 前端能打开（返回 HTML 且含 VocabBuddy）
curl -s https://你的域名/ | head

# 后端日志
# Docker:  docker compose -f deploy/docker-compose.yml logs -f app
# systemd: sudo journalctl -u vocabbuddy -f

# 常见错误
# 500 且日志报数据库连接失败  -> 检查 VOCABBUDDY_DB_URL / 数据库是否可达 / 字符集
# / 返回 404                  -> 确认 static/ 下存在 index.html 与 data.js
# 前端一直“加载中”           -> 浏览器 F12 看 /api/* 是否 401；多半是 JWT/跨域问题
```

---

## 八、运维提示

- 升级代码：拉取最新代码后 `docker compose ... up -d --build`（Docker）或
  `git pull && sudo systemctl restart vocabbuddy`（systemd）。
- 备份：定期导出 MySQL（`mysqldump vocabbuddy > backup.sql`）；用 TencentDB 则开启自动备份。
- 域名/DNS：把域名 A 记录指向 CVM 公网 IP，再申请证书。
