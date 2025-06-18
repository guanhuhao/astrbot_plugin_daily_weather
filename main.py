import aiohttp
import traceback
import re

from astrbot.api.all import (
    Star, Context, register,
    AstrMessageEvent, command_group, 
)
from astrbot.api.event import filter
from astrbot.api import logger
from typing import Optional
def format_weather_info(city: str, weather_dict):
  """
  使用正则表达式模板构造天气描述
  """
  # 定义天气描述模板
  template = city + r" {date} 周{week} 天气预报：白天{dayweather}，气温{daytemp}°C ~ {nighttemp} °C, {daywind}风{daypower}级；夜间{nightweather}， {nightwind}风{nightpower}级。"
  
  # 使用正则表达式替换占位符
  pattern = r'\{(\w+)\}'
  
  def replace_func(match):
      key = match.group(1)
      return str(weather_dict.get(key, f'{{{key}}}'))
  
  result = re.sub(pattern, replace_func, template)

  return result

async def use_LLM(result: str, config: dict) -> str:
    """
    使用 LLM 服务来润色天气预报结果
    Args:
        result: 原始天气预报文本
        config: LLM配置信息
    Returns:
        str: 润色后的天气预报文本
    """
    try:
        # 构建 prompt
        prompt = f"""
        请将以下天气预报信息，但保持信息准确性：
        
        原文：
        {result}
        
        要求：
        1. 天气现象描述要专业,使用适当emoji
        2. 可以根据天气提供小提示（列点），要让人感觉到很贴心温暖
        3. 保持所有数据的准确性
        4. 控制在150字以内
        5. 语气要以可爱的女生语气，给人带来活力满满的能量，但不要太做作

        例子：
        2024-03-19 周二 天气小播报（杭州）
        大家早安哦~ 今天白天是超美的晴天☀️呢！气温在25°C~15°C之间波动，晚上转为多云，今天风蛮大的，早上东南风3级，晚上西北风2级，记得多穿件外套哦~
        
        小贴士：
        - 今天温差有点大，记得带件外套呀~
        - 白天阳光超好，防晒霜别忘记涂哦！
        - 晚上多云很舒服，适合和朋友出去走走
        
        这么好的天气，心情都会变得超棒的！记得好好享受这个美丽的春日～
        
        """

        # 构建请求数据
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['LLM_api_key']}"
        }
        
        payload = {
            "model": config["LLM_model"],
            "messages": [
                {"role": "system", "content": "你是一个专业的天气预报员。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 200
        }

        # 使用 aiohttp 直接调用 API
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config["LLM_url"],
                headers=headers,
                json=payload,
                timeout=30
            ) as response:
                if response.status == 200:
                    response_data = await response.json()
                    logger.debug("API Response:", response_data)  # 添加调试信息
                    # 根据实际返回格式调整获取结果的方式
                    try:
                        enhanced_result = response_data['choices'][0]['message']['content'].strip()
                        return enhanced_result
                    except (KeyError, IndexError) as e:
                        logger.error(f"Response parsing error: {e}")
                        return result
                else:
                    logger.error(f"API request failed with status {response.status}")
                    response_text = await response.text()
                    logger.error(f"Error response: {response_text}")
                    return result

    except Exception as e:
        logger.error(f"LLM enhancement failed: {e}")
        logger.error(traceback.format_exc())
        return result

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
    async def weather_current(self, event: AstrMessageEvent, city: Optional[str] = ""):
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
            text = format_weather_info(city, data[0])
            # 使用 LLM 润色结果
            enhanced_text = await use_LLM(text, self.config)
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
