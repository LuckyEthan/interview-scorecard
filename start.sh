#!/bin/bash
# 面试评分系统启动脚本

cd "$(dirname "$0")"

# 检查 .env 文件（可选，用于远程 AI；本地 Ollama 可零配置启动）
if [ ! -f .env ]; then
    echo "ℹ️  未找到 .env 文件，正在从模板创建..."
    cp .env.example .env
    echo "📝 如需使用远程 AI，请编辑 .env 文件填写 API Key"
    echo "   vim .env"
    echo "   若使用本地 Ollama，可直接继续启动"
    echo ""
fi

# 检查依赖
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 安装依赖..."
    pip3 install -r requirements.txt
fi

# 启动
echo ""
python3 app.py
