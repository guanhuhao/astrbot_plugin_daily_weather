import aiohttp
import traceback
import re
import os
import json
import uuid
import datetime
import zoneinfo

from astrbot.api.all import (
    Star, Context, register,
    AstrMessageEvent, command_group,  MessageEventResult
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api.event import filter
from astrbot.api import logger, llm_tool
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from typing import Optional

def format_weather_info(city: str, weather_dict):
    """
    将天气数据格式化为可读的文本描述
    
    Args:
        city (str): 城市名称
        weather_dict (dict): 天气数据字典，包含以下字段：
            - date: 日期
            - week: 星期
            - dayweather: 白天天气
            - nightweather: 夜间天气
            - daytemp: 白天温度
            - nighttemp: 夜间温度
            - daywind: 白天风向
            - nightwind: 夜间风向
            - daypower: 白天风力
            - nightpower: 夜间风力
    
    Returns:
        str: 格式化后的天气描述文本
    """
    # 获取当前时间戳
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 定义天气描述模板
    template = f"[{current_time}]\n" + city + r" {date} 周{week} 天气预报：白天{dayweather}，气温{daytemp}°C ~ {nighttemp} °C, {daywind}风{daypower}级；夜间{nightweather}， {nightwind}风{nightpower}级。"
    
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
    "https://github.com/guanhuhao/astrbot_plugin_daily_weather.git"
)
class WeatherPlugin(Star):
    """
    基于高德开放平台API的天气查询和订阅插件。
    
    功能特点：
    1. 天气查询
       - /weather current: 查询当前实况天气
       - /weather forecast: 查询未来4天天气预报
       - /weather help: 查看帮助信息
       
    2. 天气订阅
       - /weather_subscribe sub: 订阅定时天气推送
       - /weather_subscribe ls: 查看当前订阅列表
       - /weather_subscribe rm: 删除指定订阅
       
    3. 展示方式
       - 支持文本和图片两种展示模式
       - 支持通过LLM优化展示效果
       
    4. 配置选项
       - 支持设置默认城市
       - 支持自定义API密钥
       - 支持自定义LLM提示词
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

        # subscribe init
        self.timezone = self.context.get_config().get("timezone")
        if not self.timezone:
            self.timezone = None
        try:
            self.timezone = zoneinfo.ZoneInfo(self.timezone) if self.timezone else None
        except Exception as e:
            logger.error(f"时区设置错误: {e}, 使用本地时区")
            self.timezone = None
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        subscribe_file = os.path.join(get_astrbot_data_path(), "astrbot-subscribe.json")
        if not os.path.exists(subscribe_file):
            with open(subscribe_file, "w", encoding="utf-8") as f:
                f.write("{}")
        with open(subscribe_file, "r", encoding="utf-8") as f:
            self.subscribe_data = json.load(f)

        self._init_scheduler()
        self.scheduler.start()

    def _init_scheduler(self):
        """
        初始化定时任务调度器，加载已保存的订阅任务
        
        处理两种类型的订阅：
        1. 一次性订阅 (datetime): 检查是否过期，未过期则添加到调度器
        2. 重复性订阅 (cron): 根据cron表达式添加定时任务
        
        每个订阅任务都会被分配一个唯一的UUID作为任务ID
        """
        for group in self.subscribe_data:
            for subscribe in self.subscribe_data[group]:
                if "id" not in subscribe:
                    id_ = str(uuid.uuid4())
                    subscribe["id"] = id_
                else:
                    id_ = subscribe["id"]
                if "datetime" in subscribe:
                    if self.check_is_outdated(subscribe):
                        continue
                    self.scheduler.add_job(
                        self._subscribe_callback,
                        id=id_,
                        trigger="date",
                        args=[group, subscribe],
                        run_date=datetime.datetime.strptime(
                            subscribe["datetime"], "%Y-%m-%d %H:%M"
                        ),
                        misfire_grace_time=60,
                    )
                elif "cron" in subscribe:
                    self.scheduler.add_job(
                        self._subscribe_callback,
                        trigger="cron",
                        id=id_,
                        args=[group, subscribe],
                        misfire_grace_time=60,
                        **self._parse_cron_expr(subscribe["cron"]),
                    )
                    
    def check_is_outdated(self, subscribe: dict) -> bool:
        """
        检查订阅任务是否已过期
        
        Args:
            subscribe (dict): 订阅任务信息字典，包含以下可选字段：
                - datetime: 一次性任务的执行时间，格式为 "%Y-%m-%d %H:%M"
                
        Returns:
            bool: True 表示任务已过期，False 表示任务未过期或为重复性任务
        """
        if "datetime" in subscribe:
            subscribe_time = datetime.datetime.strptime(
                subscribe["datetime"], "%Y-%m-%d %H:%M"
            ).replace(tzinfo=self.timezone)
            return subscribe_time < datetime.datetime.now(self.timezone)
        return False


    async def use_LLM(self, result: str, config: dict) -> str:
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
            if len(self.config.get("LLM_prompt", "")) < 5:
                prompt = f"""
                {result}
                请根据上面天气预报信息，润色天气预报文本，但保持信息准确性：
                
                要求：
                1. 天气现象描述要专业,使用适当emoji
                2. 可以根据天气提供小提示（列点），要让人感觉到很贴心温暖
                3. 保持所有数据的准确性
                4. 控制在150字以内
                5. 语气要以可爱的女生语气，给人带来活力满满的能量，但不要太做作
                6. 禁止使用** 或者 # 等markdown格式

                例子：
                2024-03-19 09:00 周二 天气小播报（杭州）
                大家早安哦~ 今天白天是超美的晴天☀️呢！气温在25°C~15°C之间波动，晚上转为多云，今天风蛮大的，早上东南风3级，晚上西北风2级，记得多穿件外套哦~
                
                小贴士：
                - 今天温差有点大，记得带件外套呀~
                - 白天阳光超好，防晒霜别忘记涂哦！
                - 晚上多云很舒服，适合和朋友出去走走
                
                这么好的天气，心情都会变得超棒的！记得好好享受这个美丽的春日～
                
                """
            else:
                prompt = result + "\n" + self.config.get("LLM_prompt", "")

            result = await self.context.get_using_provider().text_chat(
                    prompt=prompt,
                    # func_tool_manager=func_tools_mgr,
                    # session_id=curr_cid, # 对话id。如果指定了对话id，将会记录对话到数据库
                    # contexts=context, # 列表。如果不为空，将会使用此上下文与 LLM 对话。
                    system_prompt="",
                    image_urls=[], # 图片链接，支持路径和网络链接
                    # conversation=conversation # 如果指定了对话，将会记录对话
                )
            result = result.completion_text
            return result

        except Exception as e:
            logger.error(f"LLM enhancement failed: {e}")
            logger.error(traceback.format_exc())
            return result


    # =============================
    # 命令组 "weather"
    # =============================
    @command_group("weather", alias="天气查询")
    def weather_group(self):
        """
        天气相关功能命令组。
        使用方法：
        /weather <子指令> <城市或其它参数>
        子指令包括：
        - current: 查看当前实况天气
        - forecast: 查询未来4天天气预报
        - help: 查看帮助信息
        """
        pass

    @weather_group.command("current", alias="当前")
    async def weather_current(self, event: AstrMessageEvent, city: Optional[str] = ""):
        """
        查看当前实况天气，支持文本和图片两种展示模式，并可通过LLM优化输出格式
        用法: /weather current <城市>
        示例: /weather current 北京
        
        参数:
        - city: 城市名称，若不指定则使用默认城市
        
        输出:
        - 取决于配置的send_mode:
          - "image": 生成图片形式的天气信息
          - "text": 生成文本形式的天气信息（通过LLM优化展示）
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
            logger.info(f"original weather text={text}")
            enhanced_text = await self.use_LLM(text, self.config)
            logger.info(f"LLM enhanced weather text={enhanced_text}")
            yield event.plain_result(enhanced_text)


        # =============================
    
    
    # 命令组 "weather_subscribe"
    # =============================
    @command_group("weather_subscribe", alias="天气订阅")
    def weather_subscribe_group(self):
        """
        天气订阅相关功能命令组。
        使用方法：
        /weather_subscribe <子指令> <参数>
        
        子指令包括：
        - sub: 订阅天气预报
        - ls: 查看当前订阅列表
        - rm: 删除指定的订阅
        """
        pass
    @weather_subscribe_group.command("sub", alias="订阅")
    async def weather_subscribe(self, event: AstrMessageEvent, description: str = ""):
        """
        订阅天气预报服务
        
        Args:
            event (AstrMessageEvent): 消息事件对象
            description (str): 订阅描述，包含城市和时间信息，将通过LLM解析
                             为空时使用默认值：上海，每天9点
        
        示例:
            - /weather_subscribe sub 每天早上8点发送杭州天气
            - /weather_subscribe sub 每周一三五上午9点发送北京天气
        """
        city = "上海"
        cron_expression = "0 9 * * *"
        human_readable_cron = "每天9点"

        if description != "":
            city = await self.context.get_using_provider().text_chat(
                prompt=description,
                # func_tool_manager=func_tools_mgr,
                # session_id=curr_cid, # 对话id。如果指定了对话id，将会记录对话到数据库
                # contexts=context, # 列表。如果不为空，将会使用此上下文与 LLM 对话。
                system_prompt="请分析提取出城市名称,只需要输出城市名称如 杭州",
                image_urls=[], # 图片链接，支持路径和网络链接
                # conversation=conversation # 如果指定了对话，将会记录对话
            )
            city = city.completion_text

            cron_expression = await self.context.get_using_provider().text_chat(
                prompt=description,
                system_prompt="请分析提取出cron表达式，只需要输出cron表达式如 0 9 * * *",
                image_urls=[], # 图片链接，支持路径和网络链接
                # conversation=conversation # 如果指定了对话，将会记录对话
            )
            cron_expression = cron_expression.completion_text

            human_readable_cron = await self.context.get_using_provider().text_chat(
                prompt=city + " " + cron_expression,
                system_prompt="将输入的地点和时间转换为人类可读的格式，方便人理解，字数限制在20个字以内",
                image_urls=[], # 图片链接，支持路径和网络链接
                # conversation=conversation # 如果指定了对话，将会记录对话
            )
            human_readable_cron = human_readable_cron.completion_text


        logger.info(f"city={city}, cron_expression={cron_expression}, human_readable_cron={human_readable_cron}")


        d = {
            "text": "天气预报",
            "cron": cron_expression,
            "cron_h": human_readable_cron,
            "id": str(uuid.uuid4()),
            "city": city,
        }
        if event.unified_msg_origin not in self.subscribe_data:
            self.subscribe_data[event.unified_msg_origin] = []
        self.subscribe_data[event.unified_msg_origin].append(d)
        self.scheduler.add_job(
            self._subscribe_callback,
            "cron",
            id=d["id"],
            misfire_grace_time=60,
            **self._parse_cron_expr(cron_expression),
            args=[event.unified_msg_origin, d],
        )
        await self._save_data()
        yield event.plain_result(f"{human_readable_cron} 订阅成功")
    
    def _parse_cron_expr(self, cron_expr: str) -> dict:
        """
        解析cron表达式为APScheduler可用的参数字典
        
        Args:
            cron_expr (str): 标准cron表达式，格式为："分 时 日 月 星期"
                例如：
                - "0 9 * * *" 表示每天早上9点
                - "0 9 * * 1,3,5" 表示每周一三五早上9点
        
        Returns:
            dict: 包含以下字段的字典：
                - minute: 分钟 (0-59)
                - hour: 小时 (0-23)
                - day: 日期 (1-31)
                - month: 月份 (1-12)
                - day_of_week: 星期 (0-6 或 MON-SUN)
        """
        logger.info(f"cron_expr={cron_expr}")
        fields = cron_expr.split(" ")
        return {
            "minute": fields[0],
            "hour": fields[1],
            "day": fields[2],
            "month": fields[3],
            "day_of_week": fields[4],
        }

    async def _subscribe_callback(self, unified_msg_origin: str, d: dict):
        """
        天气订阅的回调函数，在预定时间触发并推送天气信息
        
        Args:
            unified_msg_origin (str): 消息来源的统一标识符，用于确定消息发送目标
            d (dict): 订阅任务的详细信息，包含以下字段：
                - text (str): 订阅描述文本
                - city (str): 订阅的城市名称
                - cron (str): cron表达式（用于重复性任务）
                - cron_h (str): 人类可读的时间描述
                - datetime (str, optional): 一次性任务的执行时间
                - id (str): 任务的唯一标识符
        
        处理流程：
        1. 获取指定城市的天气数据
        2. 根据配置的send_mode决定使用文本还是图片方式
        3. 如果是文本模式，使用LLM优化展示效果
        4. 发送天气信息到指定目标
        
        注意：
        - 如果获取天气数据失败，将记录错误但不重试
        - 图片模式目前标记为TODO状态
        """
        import datetime
        
        logger.info("🔔 订阅回调函数被触发！")

        try:
            city = d.get("city", "苏州")
            data = await self.get_future_weather_by_city(city)
            
            if data is None:
                logger.error(f"查询 [{city}] 的当前天气失败")
                return
            
            # 根据配置决定发送模式
            if self.send_mode == "image": # TODO
                result_img_url = await self.render_current_weather(data)
                # 发送图片消息
                await self.context.send_message(
                    unified_msg_origin,
                    MessageEventResult().image(result_img_url)
                )
            else:
                text = format_weather_info(city, data[0])
                logger.info(f"original weather text={text}")
                # 使用 LLM 润色结果
                enhanced_text = await self.use_LLM(text, self.config)
                logger.info(f"LLM enhanced weather text={enhanced_text}")
                await self.context.send_message(
                    unified_msg_origin,
                    MessageEventResult().message(enhanced_text)
                )
                
            logger.info(f"天气订阅推送成功: {city}")
            
        except Exception as e:
            logger.error(f"订阅回调执行失败: {e}", exc_info=True)
    
    @weather_subscribe_group.command("ls", alias="列表")
    async def subscribe_list(self, event: AstrMessageEvent, city: Optional[str] = ""):
        """
        列出当前所有有效的天气订阅
        
        Args:
            event (AstrMessageEvent): 消息事件对象
            city (Optional[str]): 城市名称过滤器（暂未实现）
            
        Returns:
            生成器，产生以下消息：
            - 如果没有订阅：提示没有正在进行的订阅事项
            - 如果有订阅：显示所有订阅的列表，包含序号、描述和时间
            
        订阅列表格式：
        1. 天气预报 - 每天9点(Cron: 0 9 * * *)
        2. 天气预报 - 2024-03-20 08:00
        """
        subscribe = await self.get_upcoming_subscribe(event.unified_msg_origin)
        if not subscribe:
            yield event.plain_result("没有正在进行的订阅事项。")
        else:
            subscribe_str = "正在进行的订阅事项：\n"
            for i, subscribe in enumerate(subscribe):
                time_ = subscribe.get("datetime", "")
                if not time_:
                    cron_expr = subscribe.get("cron", "")
                    time_ = subscribe.get("cron_h", "") + f"(Cron: {cron_expr})"
                subscribe_str += f"{i + 1}. {subscribe['text']} - {time_}\n"
            subscribe_str += "\n使用 /weather_subscribe rm <id> 删除订阅事项。\n"
            yield event.plain_result(subscribe_str)

    @weather_subscribe_group.command("rm", alias="删除")
    async def subscribe_rm(self, event: AstrMessageEvent, index: int):
        """
        删除指定序号的天气订阅
        
        Args:
            event (AstrMessageEvent): 消息事件对象
            index (int): 要删除的订阅序号（从1开始）
            
        Returns:
            生成器，产生以下消息之一：
            - 如果没有订阅：提示没有待办事项
            - 如果序号无效：提示索引越界
            - 如果删除成功：显示成功删除的订阅内容
            - 如果定时任务删除失败：提示可能需要重启来完全移除
            
        注意：
        - 序号对应 ls 命令显示的订阅列表序号
        - 删除后原序号之后的订阅序号会自动前移
        - 删除操作会同时移除内存中的订阅数据和定时任务
        """
        subscribe = await self.get_upcoming_subscribe(event.unified_msg_origin)

        if not subscribe:
            yield event.plain_result("没有待办事项。")
        elif index < 1 or index > len(subscribe):
            yield event.plain_result("索引越界。")
        else:
            subscribe = subscribe.pop(index - 1)
            job_id = subscribe.get("id")

            users_subscribe = self.subscribe_data.get(event.unified_msg_origin, [])
            for i, s in enumerate(users_subscribe):
                if s.get("id") == job_id:
                    users_subscribe.pop(i)

            try:
                self.scheduler.remove_job(job_id)
            except Exception as e:
                logger.error(f"Remove job error: {e}")
                yield event.plain_result(
                    f"成功移除对应的待办事项。删除定时任务失败: {str(e)} 可能需要重启 AstrBot 以取消该提醒任务。"
                )
            await self._save_data()
            yield event.plain_result("成功删除待办事项：\n" + subscribe["text"])

    async def get_upcoming_subscribe(self, unified_msg_origin: str):
        """Get upcoming subscribe."""
        subscribe = self.subscribe_data.get(unified_msg_origin, [])
        if not subscribe:
            return []
        now = datetime.datetime.now(self.timezone)
        upcoming_subscribe = [
            subscribe
            for subscribe in subscribe
            if "datetime" not in subscribe
            or datetime.datetime.strptime(
                subscribe["datetime"], "%Y-%m-%d %H:%M"
            ).replace(tzinfo=self.timezone)
            >= now
        ]
        return upcoming_subscribe

    async def _save_data(self):
        """Save the subscribe data."""
        subscribe_file = os.path.join(get_astrbot_data_path(), "astrbot-subscribe.json")
        with open(subscribe_file, "w", encoding="utf-8") as f:
            json.dump(self.subscribe_data, f, ensure_ascii=False)
    
    
    # =============================
    # 核心逻辑
    # =============================
    async def get_future_weather_by_city(self, city: str) -> Optional[list]:
        """
        调用高德开放平台API，获取城市未来天气预报
        
        Args:
            city (str): 城市名称或城市编码
            
        Returns:
            Optional[list]: 天气预报数据列表，每个元素为一天的天气数据字典
                          如果请求失败则返回 None
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

    async def terminate(self):
        self.scheduler.shutdown()
        await self._save_data()
        logger.info("weather_subscribe plugin terminated.")