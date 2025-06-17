# -*- coding: utf-8 -*-
import aiohttp
import os
from typing import Optional
import traceback
import re
from openai import AsyncOpenAI

from astrbot.api.all import (
    Star, Context, register,
    AstrMessageEvent, command_group, 
)
from astrbot.api.event import filter
from astrbot.api import logger

def use_LLM(result):
  return result

def format_weather_info(weather_dict):
  """
  使用正则表达式模板构造天气描述
  """
  # 定义天气描述模板
  template = r"{date} 周{week} 天气预报：白天{dayweather}，气温{daytemp}°C ~ {nighttemp} °C, {daywind}风{daypower}级；夜间{nightweather}， {nightwind}风{nightpower}级。"
  
  # 使用正则表达式替换占位符
  pattern = r'\{(\w+)\}'
  
  def replace_func(match):
      key = match.group(1)
      return str(weather_dict.get(key, f'{{{key}}}'))
  
  result = re.sub(pattern, replace_func, template)

  return result

async def use_LLM(result: str , config: dict) -> str:
    """
    使用 LLM 服务来润色天气预报结果
    Args:
        result: 原始天气预报文本
    Returns:
        str: 润色后的天气预报文本
    """
    try:
        # 初始化 OpenAI 客户端
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", config["LLM_api_key"]),
            base_url=os.getenv("OPENAI_API_BASE", config["LLM_url"])  # 可以设置为其他兼容的API端点
        )

        # 构建 prompt
        if config["LLM_prompt"] is "":
          prompt = f"""
          请将以下天气预报信息改写得更加自然、生动，但保持信息准确性：
          
          原文：
          {result}
          
          要求：
          1. 使用更生动的语言
          2. 可以添加适当的表情符号
          3. 可以根据天气增加合适的建议
          4. 保持所有数据的准确性
          5. 控制在200字以内
          """

        # 调用 API
        response = await client.chat.completions.create(
            model=config["LLM_model"],  # 或其他兼容的模型
            messages=[
                {"role": "system", "content": "你是一个专业的天气预报员，善于用生动有趣的语言描述天气。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )

        # 获取结果
        enhanced_result = response.choices[0].message.content.strip()
        return enhanced_result

    except Exception as e:
        logger.error(f"LLM enhancement failed: {e}")
        logger.error(traceback.format_exc())
        return result  # 如果失败则返回原始结果

@register(
    "daily_weather",
    "Guan",
    "一个基于高德开放平台API的天气查询插件",
    "1.0.0",
    "https://github.com/guanhuhao/astrbot_plugin_daily_weather.git"
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
            # 使用 LLM 润色结果
            enhanced_text = await use_LLM(text, self.config)
            print(data)
            yield event.plain_result(enhanced_text)

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