# -*- coding: utf-8 -*-
import aiohttp
import datetime
from typing import Optional, List, Dict
import traceback

from astrbot.api.all import (
    Star, Context, register,
    AstrMessageEvent, command_group, command,
    MessageEventResult, llm_tool
)
from astrbot.api.event import filter
from astrbot.api import logger

# ==============================
# 1) HTML 模板
# ==============================

CURRENT_WEATHER_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 1280px; /* 确保匹配 render 预设的图片尺寸 */
      height: 720px;
      background-color: #fff;
    }
    .weather-container {
      width: 100%;
      height: 100%;
      padding: 8px;
      display: flex;
      flex-direction: column;
      justify-content: center; /* 垂直居中 */
      align-items: center; /* 水平居中 */
      background-color: #ffffff;
      color: #333;
      font-family: sans-serif;
      font-size: 30px;
      border: 1px solid #ddd;
      border-radius: 8px;
    }
    .weather-container h2 {
      margin-top: 0;
      color: #4e6ef2;
      text-align: center;
      font-size: 40px;
    }
    .weather-info {
      margin-bottom: 10px;
    }
    .source-info {
      border-top: 1px solid #ddd;
      margin-top: 12px;
      padding-top: 12px;
      font-size: 16px;
      color: #999;
    }
  </style>
</head>
<body>
  <div class="weather-container">
    <h2>当前天气</h2>
    
    <div class="weather-info">
      <strong>城市:</strong> {{ city }}
    </div>
    <div class="weather-info">
      <strong>天气:</strong> {{ desc }}
    </div>
    <div class="weather-info">
      <strong>温度:</strong> {{ temp }}℃ (体感: {{ feels_like }}℃)
    </div>
    <div class="weather-info">
      <strong>湿度:</strong> {{ humidity }}%
    </div>
    <div class="weather-info">
      <strong>风速:</strong> {{ wind_speed }} km/h
    </div>
    
    <div class="source-info">
      数据来源: 心知天气（Seniverse） 免费API
    </div>
  </div>
</body>
</html>
"""

FORECAST_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 1280px;
      height: 720px;
      background-color: #fff;
    }
    .forecast-container {
      width: 100%;
      height: 100%;
      padding: 8px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      background-color: #fff;
      color: #333;
      font-family: sans-serif;
      font-size: 30px;
      border: 1px solid #ddd;
      border-radius: 8px;
    }
    .forecast-container h2 {
      margin-top: 0;
      color: #4e6ef2;
      text-align: center;
      font-size: 40px;
    }
    .city-info {
      margin-bottom: 8px;
    }
    .day-item {
      margin-bottom: 8px;
      border-bottom: 1px solid #eee;
      padding-bottom: 4px;
    }
    .day-title {
      font-weight: bold;
      color: #4e6ef2;
      margin-bottom: 4px;
    }
    .source-info {
      font-size: 16px;
      color: #999;
      margin-top: 12px;
      border-top: 1px solid #ddd;
      padding-top: 8px;
    }
  </style>
</head>
<body>
  <div class="forecast-container">
    <h2>未来{{ total_days }}天天气预报</h2>
    <div class="city-info">
      <strong>城市:</strong> {{ city }}
    </div>

    {% for day in days %}
    <div class="day-item">
      <div class="day-title">{{ day.date }}</div>
      <div><strong>白天:</strong> {{ day.text_day }} — {{ day.high }}℃</div>
      <div><strong>夜晚:</strong> {{ day.text_night }} — {{ day.low }}℃</div>
      <div><strong>湿度:</strong> {{ day.humidity }}%  <strong>风速:</strong> {{ day.wind_speed }} km/h</div>
    </div>
    {% endfor %}

    <div class="source-info">
      数据来源: 高德开放平台（Amap） 免费API
    </div>
  </div>
</body>
</html>
"""


def format_weather_info(weather_dict):
  """
  使用正则表达式模板构造天气描述
  """
  # 定义天气描述模板
  template = r"{date}周{week} 天气预报：白天{dayweather}，气温{daytemp}°C ~ {nighttemp} °C, {daywind}风{daypower}级；夜间{nightweather}，{nightwind}风{nightpower}级。"
  
  # 使用正则表达式替换占位符
  pattern = r'\{(\w+)\}'
  
  def replace_func(match):
      key = match.group(1)
      return str(weather_dict.get(key, f'{{{key}}}'))
  
  result = re.sub(pattern, replace_func, template)
  return result

@register(
    "daily_weather",
    "Guan",
    "一个基于高德开放平台API的天气查询插件",
    "1.0.0",
    "https://github.com/BB0813/astrbot_plugin_weather-Amap"
)
class WeatherPlugin(Star):
    """
    这是一个调用高德开放平台API的天气查询插件示例。
    支持 /weather current /weather forecast /weather help
    - current: 查询当前实况
    - forecast: 查询未来4天天气预报
    """
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        # 使用配置中的 amap_api_key
        self.api_key = config.get("amap_api_key", "")
        self.default_city = config.get("default_city", "北京")
        # 新增配置项：send_mode，控制发送模式 "image" 或 "text"
        self.send_mode = config.get("send_mode", "image")
        logger.debug(f"WeatherPlugin initialized with API key: {self.api_key}, default_city: {self.default_city}, send_mode: {self.send_mode}")

    # =============================
    # 命令组 "weather"
    # =============================
    @command_group("weather")
    def weather_group(self):
        """
        天气相关功能命令组。
        使用方法：
        /weather <子指令> <城市或其它参数>
        子指令包括：current, forecast, help
        """
        pass

    @weather_group.command("current")
    async def weather_current(self, event: AstrMessageEvent, city: Optional[str] = "苏州"):
        """
        查看当前实况天气
        用法: /weather current <城市>
        示例: /weather current 北京
        """
        logger.info(f"User called /weather current with city={city}")
        if not city:
            city = self.default_city
        if not self.api_key:
            yield event.plain_result("未配置 Amap API Key，无法查询天气。请在管理面板中配置后再试。")
            return
        data = await self.get_future_weather_by_city(city)
        if data is None:
            yield event.plain_result(f"查询 [{city}] 的当前天气失败，请稍后再试。")
            return
        # 根据配置决定发送模式
        if self.send_mode == "image":
            result_img_url = await self.render_current_weather(data)
            yield event.image_result(result_img_url)
        else:
            text = format_weather_info(data[0])
            print(data)
            yield event.plain_result(text)

    # =============================
    # 核心逻辑
    # =============================
    async def get_future_weather_by_city(self, city: str) -> Optional[list]:
        """
        调用高德开放平台API，返回城市当前实况
        """
        logger.debug(f"get_current_weather_by_city city={city}")
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            "key": self.api_key,
            "city": city,
            "extensions": "all"
        }
        logger.debug(f"Requesting: {url}, params={params}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    logger.debug(f"Response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        weather_list = []
                        for daily_weather in data['forecasts'][0]['casts']:
                              weather_list.append(daily_weather)

                        return weather_list
                    else:
                        logger.error(f"get_current_weather_by_city status={resp.status}")
                        return None
        except Exception as e:
            logger.error(f"get_current_weather_by_city error: {e}")
            logger.error(traceback.format_exc())
            return None


# if __name__ == "__main__":
#     import re
#     def format_weather_info(weather_dict):
#       """
#       使用正则表达式模板构造天气描述
#       """
#       # 定义天气描述模板
#       template = r"{date}周{week} 天气预报：白天{dayweather}，气温{daytemp}°C ~ {nighttemp} °C, {daywind}风{daypower}级；夜间{nightweather}，{nightwind}风{nightpower}级。"
      
#       # 使用正则表达式替换占位符
#       pattern = r'\{(\w+)\}'
      
#       def replace_func(match):
#           key = match.group(1)
#           return str(weather_dict.get(key, f'{{{key}}}'))
      
#       result = re.sub(pattern, replace_func, template)
#       return result

#     async def get_current_weather_by_city(city: str) -> Optional[list]:
#         """
#         调用高德开放平台API，返回城市当前实况
#         """
#         # logger.debug(f"get_current_weather_by_city city={city}")
#         url = "https://restapi.amap.com/v3/weather/weatherInfo"
#         params = {
#             "key": "05e0e64017d1466e2f0bb654688553f6",
#             "city": city,
#             "extensions": "all"
#         }
#         # logger.debug(f"Requesting: {url}, params={params}")
#         try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.get(url, params=params, timeout=10) as resp:
#                     # logger.debug(f"Response status: {resp.status}")
#                     if resp.status == 200:
#                         data = await resp.json()
#                         # print(data)
#                         weather_list = []
#                         for daily_weather in data['forecasts'][0]['casts']:
#                               weather_list.append(daily_weather)

#                         return weather_list
#                     else:
#                         # logger.error(f"get_current_weather_by_city status={resp.status}")
#                         return None
#         except Exception as e:
#             # logger.error(f"get_current_weather_by_city error: {e}")
#             # logger.error(traceback.format_exc())
#             return None

#     # 创建事件循环来运行异步函数
#     import asyncio
#     async def main():
#         result = await get_current_weather_by_city("苏州")
#         print(result)

#     # 运行异步主函数
#     asyncio.run(main())