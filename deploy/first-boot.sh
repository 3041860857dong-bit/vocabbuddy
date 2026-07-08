#!/usr/bin/env bash
#
# VocabBuddy 首次上机初始化脚本
# 运行环境：腾讯云 CVM，Ubuntu 22.04+，以具有 sudo 权限的普通用户执行
# 前置条件：
#   1) 已购买 CVM 并拿到公网 IP
#   2) 已创建 TencentDB for MySQL（8.0），记下地址 / 账号 / 密码
#   3) 已把本 CVM 的 IP 加入 TencentDB 白名单 / 安全组
#   4) 项目文件已上传到本机 ~/vocabbuddy（或 git clone 下来）
#
# 用法：
#   chmod +x deploy/first-boot.sh
#   ./deploy/first-boot.sh          # 首次会生成 .env 并提示你填写，填完再跑一次
#   ./deploy/first-boot.sh          # 第二次真正构建、启动、导词库、验证
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "== [1/6] 系统更新与基础工具 =="
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git

echo "== [2/6] 安装 Docker =="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.daocloud.io/docker | bash
  sudo systemctl enable --now docker
fi
# 让当前用户免 sudo 使用 docker（需重新登录生效；本脚本继续用 sudo）
sudo usermod -aG docker "$USER" 2>/dev/null || true

echo "== [3/6] 配置 .env =="
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/deploy/.env.server.example" "$APP_DIR/.env"
  echo "---------------------------------------------------------------"
  echo "已生成 $APP_DIR/.env，请编辑并至少填好："
  echo "  VOCABBUDDY_DB_URL      -> TencentDB 连接串（内网地址）"
  echo "  VOCABBUDDY_JWT_SECRET  -> 随机长字符串（文件内有生成命令）"
  echo "  VOCABBUDDY_LLM_API_KEY -> 不填也能跑，仅混淆/同义词功能降级"
  echo "填完后重新运行本脚本完成后续步骤。"
  echo "---------------------------------------------------------------"
  exit 0
fi

echo "== [4/6] 构建并启动应用（仅应用，数据库用 TencentDB）=="
sudo docker compose --env-file "$APP_DIR/.env" -f "$APP_DIR/deploy/docker-compose.yml" up -d --build

echo "== [5/6] 等待 /health 就绪 =="
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "应用已就绪"
    break
  fi
  sleep 2
done

echo "== [6/6] 导入词库 =="
sudo docker compose --env-file "$APP_DIR/.env" -f "$APP_DIR/deploy/docker-compose.yml" exec -T app python -m backend.import_words

echo "== 完成 =="
curl -fsS http://127.0.0.1:8000/health && echo " <- health OK"
echo "浏览器访问： http://<你的CVM公网IP>:8000"
