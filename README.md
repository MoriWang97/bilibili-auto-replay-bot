# bilibili-bot

B站评论区 AI 自动回复机器人 — 被 @后自动总结视频内容并回复。

## 架构设计

```
src/
├── bilibili/          # B站 API 层 (Adapter Pattern)
│   ├── client.py      # HTTP 客户端，封装 B站 API
│   └── models.py      # 数据模型
├── ai/                # AI 层 (Strategy Pattern)
│   ├── base.py        # 抽象策略接口
│   └── azure_openai.py  # Azure OpenAI 具体策略
├── bot/               # 业务逻辑层
│   ├── monitor.py     # @提醒轮询器
│   ├── processor.py   # 消息处理编排
│   └── cache.py       # 视频总结缓存 (Proxy Pattern)
└── config/
    └── settings.py    # 配置管理
```

**设计模式**:
- **Strategy**: AI 提供商可替换 (Azure OpenAI / 其他)
- **Adapter**: 封装 B站 API 为统一接口
- **Proxy (Cache)**: 缓存视频总结，节省 AI 调用费用

## 前置准备

### 1. 获取 B站 Cookie

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. F12 → Application → Cookies → 复制 `SESSDATA` 和 `bili_jct`
3. 也可以复制完整的 Cookie 字符串

### 2. Azure OpenAI 配置

准备以下信息：
- Azure OpenAI Endpoint（如 `https://xxx.openai.azure.com/`）
- API Key
- 部署名称（如 `gpt-52`）

### 3. 获取自己的 B站 UID

登录 B站后访问个人空间，URL 中的数字即为 UID。

## 安装 & 运行

```bash
# 1. 安装依赖
pip install -e .

# 2. 复制配置文件
cp config/config.example.yaml config/config.yaml

# 3. 编辑配置
# 填入你的 B站 Cookie 和 Azure OpenAI 信息

# 4. 运行
python run.py
```

## 配置说明

参见 `config/config.example.yaml`，关键配置项：

| 配置项 | 说明 |
|--------|------|
| `bilibili.sessdata` | B站登录凭证 |
| `bilibili.bili_jct` | B站 CSRF Token |
| `bilibili.uid` | 你自己的 B站 UID |
| `azure_openai.endpoint` | Azure OpenAI 端点 |
| `azure_openai.api_key` | Azure OpenAI 密钥 |
| `azure_openai.deployment` | 模型部署名称 |
| `bot.poll_interval` | 轮询间隔（秒），建议 30-60 |
| `bot.max_subtitle_chars` | 字幕最大字符数，控制 token 用量 |

## 省钱策略

1. **字幕优先**：使用 AI 生成的 CC 字幕文本，而非视频流
2. **缓存总结**：同一视频只调用一次 AI（TTL 可配置）
3. **控制字幕长度**：截断过长字幕，减少 token 消耗
4. **调节轮询频率**：30-60 秒一次，避免被 B站风控

## License

MIT
