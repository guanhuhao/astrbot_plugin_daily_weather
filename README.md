# 高德天气查询与订阅插件

一个基于高德开放平台 API 的天气查询和订阅插件，支持查询当前天气和未来天气预报，提供定时天气订阅服务，并使用 LLM 进行结果优化展示。

## 功能特点

### 天气查询
- 支持查询当前天气状况
- 支持查询未来天气预报
- 支持文本和图片两种展示模式
- 支持自定义默认城市
- 支持 LLM 优化天气描述，让天气播报更生动有趣

### 天气订阅
- 支持定时天气推送服务
- 支持自定义订阅时间（Cron表达式）
- 支持多城市订阅
- 支持订阅管理（查看、删除）
- 支持自然语言订阅描述

## 安装说明

1. 安装依赖包：
```bash
pip install -r requirements.txt
```

2. 确保你的 Python 环境中有以下依赖：
- aiohttp>=3.8.0
- apscheduler
- zoneinfo (Python 3.9+ 内置)

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
    "LLM_prompt": {
        "description": "自定义 Prompt",
        "type": "string",
        "hint": "自定义天气描述的优化提示词"
    }
}
```

## 使用方法

### 天气查询命令

```
/weather <子命令> [城市名]
```

#### 支持的子命令
- `current`: 查询当前天气
  - 示例：`/weather current 苏州`
- `help`: 显示帮助信息

### 天气订阅命令

```
/weather_subscribe <子命令> [参数]
```

#### 支持的子命令
- `sub`: 订阅天气预报
  - 示例：`/weather_subscribe sub 每天早上8点发送杭州天气`
  - 示例：`/weather_subscribe sub 每周一三五上午9点发送北京天气`
- `ls`: 查看当前订阅列表
- `rm <序号>`: 删除指定序号的订阅
  - 示例：`/weather_subscribe rm 1`

### 天气信息展示格式

#### 基础文本格式
```
[时间戳]
[城市] [日期] 周[星期] 天气预报：
白天[天气]，气温[高温]°C ~ [低温]°C, [风向]风[风力]级；
夜间[天气]，[风向]风[风力]级。
```

#### LLM 优化格式
LLM 会将基础天气信息转化为更生动、友好的格式，包括：
- 更自然的语言描述
- 适当的表情符号
- 贴心的天气建议
- 温暖活力的语气

示例：
```
2024-03-19 09:00 周二 天气小播报（杭州）
大家早安哦~ 今天白天是超美的晴天☀️呢！气温在25°C~15°C之间波动，晚上转为多云，今天风蛮大的，早上东南风3级，晚上西北风2级，记得多穿件外套哦~

小贴士：
- 今天温差有点大，记得带件外套呀~
- 白天阳光超好，防晒霜别忘记涂哦！
- 晚上多云很舒服，适合和朋友出去走走

这么好的天气，心情都会变得超棒的！记得好好享受这个美丽的春日～
```

## 依赖要求

- Python 3.9+
- aiohttp>=3.8.0
- apscheduler
- AstrBot 框架

## 作者信息

- 作者：鸽吾安
- 版本：1.0.0
- 项目地址：https://github.com/guanhuhao/astrbot_plugin_daily_weather
