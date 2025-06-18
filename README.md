# 高德天气查询插件

一个基于高德开放平台 API 的天气查询插件，支持查询当前天气和未来天气预报，并使用 LLM 进行结果优化展示。

## 功能特点

- 支持查询当前天气状况
- 支持查询未来天气预报
- 支持文本和图片两种展示模式
- 支持自定义默认城市
- 支持 LLM 优化天气描述，让天气播报更生动有趣

## 安装说明

1. 安装依赖包：
```bash
pip install aiohttp>=3.8.0
```

2. 确保你的 Python 环境中有以下模块：
- re (Python 内置模块，用于正则表达式处理)

## 配置说明

在 `_conf_schema.json` 中配置以下参数：

```json
{
    "amap_api_key": {
        "description": "高德开放平台 API Key",
        "type": "string",
        "hint": "请前往 https://lbs.amap.com/ 注册并获取 API Key"
    },
    "default_city": {
        "description": "默认城市",
        "type": "string",
        "default": "上海"
    },
    "send_mode": {
        "description": "发送模式",
        "type": "string",
        "options": ["text", "image"],
        "default": "text"
    },
    "LLM_api_key": {
        "description": "LLM API Key",
        "type": "string",
        "hint": "请使用openai格式的api key"
    },
    "LLM_url": {
        "description": "LLM API URL",
        "type": "string",
        "hint": "请使用对应服务商的url"
    },
    "LLM_model": {
        "description": "LLM Model",
        "type": "string",
        "hint": "请使用对应服务商的模型"
    },
    "LLM_prompt": {
        "description": "自定义 Prompt",
        "type": "string",
        "hint": "自定义Prompt"
    }
}
```

## 使用方法

### 命令格式

```
/weather <子命令> [城市名]
```

### 支持的子命令

- `current`: 查询当前天气
  - 示例：`/weather current 苏州`
- `forecast`: 查询天气预报
  - 示例：`/weather forecast 北京`
- `help`: 显示帮助信息

### 天气信息展示格式

#### 基础文本格式
```
[日期]周[星期] 天气预报：
白天[天气]，气温[高温]°C ~ [低温]°C, [风向]风[风力]级；
夜间[天气]，[风向]风[风力]级。
```

#### LLM 优化格式
LLM 会将基础天气信息转化为更生动、友好的格式，包括：
- 更自然的语言描述
- 适当的表情符号
- 贴心的天气建议
- 温暖活力的语气

## 依赖要求

- Python 3.7+
- aiohttp (外部依赖，用于HTTP请求)
- re (Python内置模块，用于正则表达式)
- AstrBot 框架

## 作者信息

- 作者：鸽吾安
- 版本：1.0.0
- 项目地址：https://github.com/guanhuhao/astrbot_plugin_daily_weather#
