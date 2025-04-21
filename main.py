#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成语接龙插件 - 提供群聊成语接龙游戏功能
重写版 - 使用更可靠的实现方式
"""
import os
import time
import json
import aiohttp
import tomllib
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

from loguru import logger

# 导入插件基类和工具
from utils.plugin_base import PluginBase
from utils.decorators import *
from WechatAPI import WechatAPIClient

# 尝试导入积分管理插件
try:
    from plugins.AdminPoint.main import AdminPoint
    HAS_ADMIN_POINT = True
except ImportError:
    HAS_ADMIN_POINT = False
    logger.warning("未找到AdminPoint插件，积分功能将不可用")

# 尝试导入昵称同步插件
try:
    from plugins.NicknameSync.main import NicknameDatabase
except ImportError:
    NicknameDatabase = None
    logger.warning("未找到NicknameSync插件，昵称显示可能不完整")

@dataclass
class GameSession:
    """游戏会话数据"""
    chatroom_id: str  # 群聊ID
    game_id: str  # 游戏ID
    current_idiom: str  # 当前成语
    last_player: Optional[str] = None  # 上一个接龙成功的玩家ID
    active: bool = True  # 游戏是否进行中
    players: Dict[str, int] = field(default_factory=dict)  # 玩家得分 {wxid: score}
    consecutive_players: Dict[str, int] = field(default_factory=dict)  # 连续接龙次数 {wxid: count}
    total_idioms_count: Dict[str, int] = field(default_factory=dict)  # 每个玩家成功接龙的总次数 {wxid: count}
    start_time: float = field(default_factory=time.time)  # 游戏开始时间
    last_activity_time: float = field(default_factory=time.time)  # 最后活动时间
    reminder_sent: bool = False  # 是否已发送提醒
    used_idioms: List[str] = field(default_factory=list)  # 已使用的成语列表

class IdiomSolitaire(PluginBase):
    """成语接龙插件，提供群聊成语接龙游戏"""
    
    description = "成语接龙插件 - 根据上一个成语的最后一个字接新成语"
    author = "wspzf"
    version = "1.0.0"
    
    def __init__(self):
        super().__init__()
        
        # 获取配置文件路径
        self.plugin_dir = os.path.dirname(__file__)
        config_path = os.path.join(self.plugin_dir, "config.toml")
        
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            game_config = config.get("IdiomSolitaire", {})
            self.enable = game_config.get("enable", True)
            self.commands = game_config.get("commands", ["成语接龙", "接龙游戏", "开始接龙"])
            self.command_tip = game_config.get("command-tip", "")
            
            # 结束游戏命令
            self.end_commands = game_config.get("end-commands", ["游戏结束", "结束接龙", "结束游戏"])
            
            # 游戏设置
            self.round_timeout = game_config.get("round-timeout", 60)  # 每轮超时时间(秒)
            self.reminder_time = game_config.get("reminder-time", 30)  # 提醒时间(秒)
            self.mode = game_config.get("mode", "exact")  # 接龙模式
            self.allow_repeat = game_config.get("allow-repeat", False)  # 是否允许重复成语
            
            # 本地判断设置
            self.local_check = game_config.get("local-check", True)  # 是否进行本地判断
            self.cache_used_idioms = game_config.get("cache-used-idioms", True)  # 是否缓存已使用成语
            
            # API设置
            self.api_url = game_config.get("api-url", "https://api.dudunas.top/api/chengyujielong")
            self.app_secret = game_config.get("app-secret", "6213a471bd150b1626bdd6c3a416c1aa")
            
            # 积分设置
            self.base_points = game_config.get("base-points", 5)  # 基础积分
            self.bonus_points = game_config.get("bonus-points", 2)  # 连续接龙奖励积分
            
            # 错误处理设置
            self.error_cooldown = game_config.get("error-cooldown", 5)  # 错误提示冷却时间(秒)
            self.show_error_tips = game_config.get("show-error-tips", True)  # 是否显示错误提示
            
            # 持久化设置
            self.enable_persistence = game_config.get("enable-persistence", True)  # 是否启用持久化
            self.sessions_file = os.path.join(self.plugin_dir, "sessions.json")  # 会话存储文件
            
            # 调试设置
            self.debug_mode = game_config.get("debug-mode", False)
            
            # 设置日志级别
            if self.debug_mode:
                logger.level("DEBUG")
                logger.debug("成语接龙调试模式已启用")
            
            # 游戏会话和错误记录
            self.game_sessions: Dict[str, GameSession] = {}
            self.error_records: Dict[str, Dict[str, float]] = {}
            
            # 加载持久化的会话数据
            if self.enable_persistence:
                self._load_sessions()
            
            logger.success("成语接龙插件初始化成功")
            
        except Exception as e:
            logger.error(f"加载成语接龙插件配置文件失败: {str(e)}")
            self.enable = False
    
    def _load_sessions(self):
        """从文件加载游戏会话数据"""
        if not os.path.exists(self.sessions_file):
            if self.debug_mode:
                logger.debug("会话存储文件不存在，将创建新文件")
            return
        
        try:
            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                sessions_data = json.load(f)
            
            for chatroom_id, session_data in sessions_data.items():
                # 检查会话是否过期
                last_activity_time = session_data.get('last_activity_time', 0)
                if time.time() - last_activity_time > self.round_timeout * 2:
                    # 会话已过期，不恢复
                    if self.debug_mode:
                        logger.debug(f"会话已过期，不恢复: {chatroom_id}")
                    continue
                
                # 创建GameSession对象
                game_session = GameSession(
                    chatroom_id=session_data.get('chatroom_id', ''),
                    game_id=session_data.get('game_id', ''),
                    current_idiom=session_data.get('current_idiom', ''),
                    last_player=session_data.get('last_player'),
                    active=session_data.get('active', False),
                    start_time=session_data.get('start_time', time.time()),
                    last_activity_time=session_data.get('last_activity_time', time.time()),
                    reminder_sent=session_data.get('reminder_sent', False),
                )
                
                # 恢复字典类型的字段
                game_session.players = session_data.get('players', {})
                game_session.consecutive_players = session_data.get('consecutive_players', {})
                game_session.total_idioms_count = session_data.get('total_idioms_count', {})
                game_session.used_idioms = session_data.get('used_idioms', [])
                
                # 添加到游戏会话字典
                self.game_sessions[chatroom_id] = game_session
            
            active_count = sum(1 for session in self.game_sessions.values() if session.active)
            logger.info(f"已加载 {len(self.game_sessions)} 个游戏会话，其中 {active_count} 个活跃会话")
            
        except Exception as e:
            logger.error(f"加载游戏会话数据失败: {str(e)}")
    
    def _save_sessions(self):
        """将游戏会话数据保存到文件"""
        if not self.enable_persistence:
            return
        
        try:
            # 将GameSession对象转换为字典
            sessions_data = {}
            for chatroom_id, session in self.game_sessions.items():
                if not session.active:
                    # 不保存非活跃会话
                    continue
                
                # 使用dataclasses的asdict将对象转为字典
                session_dict = asdict(session)
                sessions_data[chatroom_id] = session_dict
            
            # 将字典保存为JSON文件
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(sessions_data, f, ensure_ascii=False, indent=2)
            
            if self.debug_mode:
                logger.debug(f"已保存 {len(sessions_data)} 个活跃游戏会话到文件")
                
        except Exception as e:
            logger.error(f"保存游戏会话数据失败: {str(e)}")
    
    async def async_init(self):
        """异步初始化，注册定时任务"""
        logger.info("成语接龙插件异步初始化")
    
    @schedule('interval', seconds=1)
    async def check_game_sessions(self, bot: WechatAPIClient):
        """定时检查游戏会话，处理超时和提醒"""
        if not self.enable or not self.game_sessions:
            return
        
        if self.debug_mode:
            logger.debug(f"定时检查游戏会话，当前活跃游戏数: {len(self.game_sessions)}")
        
        current_time = time.time()
        sessions_to_end = []
        sessions_modified = False
        
        for chatroom_id, session in list(self.game_sessions.items()):
            if not session.active:
                continue
            
            # 计算距离上次活动的时间
            elapsed_time = current_time - session.last_activity_time
            remaining_time = self.round_timeout - elapsed_time
            
            # 如果超时，结束游戏
            if elapsed_time >= self.round_timeout:
                if self.debug_mode:
                    logger.debug(f"群 {chatroom_id} 的游戏已超时 {elapsed_time:.1f} 秒，将结束游戏")
                
                sessions_to_end.append(chatroom_id)
                sessions_modified = True
                
            # 如果接近超时且未发送提醒，发送提醒
            elif remaining_time <= self.reminder_time and not session.reminder_sent:
                if self.debug_mode:
                    logger.debug(f"群 {chatroom_id} 的游戏即将超时，还剩 {int(remaining_time)} 秒，发送提醒")
                
                session.reminder_sent = True
                sessions_modified = True
                
                try:
                    await bot.send_text_message(
                        chatroom_id,
                        f"⏰ 成语接龙即将超时！\n当前成语：{session.current_idiom}\n还剩 {int(remaining_time)} 秒"
                    )
                    if self.debug_mode:
                        logger.debug(f"已发送超时提醒: 群={chatroom_id}, 剩余时间={int(remaining_time)}秒")
                except Exception as e:
                    logger.error(f"发送超时提醒时出错: {str(e)}")
        
        # 结束超时的游戏
        for chatroom_id in sessions_to_end:
            try:
                if self.debug_mode:
                    logger.debug(f"结束超时游戏: 群={chatroom_id}")
                
                # 直接标记为非活动状态，防止重复结束
                if chatroom_id in self.game_sessions:
                    self.game_sessions[chatroom_id].active = False
                
                await self._end_game(bot, chatroom_id)
            except Exception as e:
                logger.error(f"结束超时游戏时出错: {str(e)}")
                
                # 确保清理不成功的游戏会话
                if chatroom_id in self.game_sessions:
                    logger.warning(f"强制清理游戏会话: 群={chatroom_id}")
                    del self.game_sessions[chatroom_id]
                if chatroom_id in self.error_records:
                    del self.error_records[chatroom_id]
        
        # 如果有会话状态变更，保存会话数据
        if sessions_modified and self.enable_persistence:
            self._save_sessions()
    
    @on_text_message(priority=50)
    async def handle_message(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return
        
        try:
            content = str(message.get("Content", "")).strip()
            from_wxid = message.get("FromWxid", "")
            sender_wxid = message.get("SenderWxid", "")
            
            # 判断是否是群聊
            if not from_wxid.endswith("@chatroom"):
                return
            
            # 处理开始游戏命令
            if content in self.commands:
                await self._start_game(bot, from_wxid)
                return
            
            # 处理结束游戏命令
            if content in self.end_commands and from_wxid in self.game_sessions and self.game_sessions[from_wxid].active:
                await self._end_game(bot, from_wxid)
                return
            
            # 处理接龙
            if from_wxid in self.game_sessions and self.game_sessions[from_wxid].active:
                await self._handle_idiom(bot, message)
        except Exception as e:
            logger.error(f"处理文本消息时出错: {str(e)}")
    
    async def _start_game(self, bot: WechatAPIClient, chatroom_id: str):
        """开始游戏"""
        # 如果已有游戏在进行，先结束它
        if chatroom_id in self.game_sessions and self.game_sessions[chatroom_id].active:
            await bot.send_text_message(chatroom_id, "⚠️ 已有成语接龙游戏正在进行，将重新开始游戏")
            self.game_sessions[chatroom_id].active = False
        
        try:
            # 调用API开始游戏
            async with aiohttp.ClientSession() as http_session:
                # 根据API文档，参数为start、mode和AppSecret
                params = {
                    "AppSecret": self.app_secret,
                    "start": "true",
                    "mode": self.mode
                }
                
                if self.debug_mode:
                    logger.debug(f"发起游戏开始API请求: {self.api_url}，参数: {params}")
                
                async with http_session.get(self.api_url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"API请求失败，状态码: {response.status}")
                        await bot.send_text_message(chatroom_id, "❌ 游戏开始失败，API请求错误")
                        return
                    
                    try:
                        data = await response.json()
                    except Exception as e:
                        logger.error(f"解析API响应JSON失败: {str(e)}")
                        await bot.send_text_message(chatroom_id, "❌ 游戏开始失败，API响应格式错误")
                        return
                    
                    if self.debug_mode:
                        logger.debug(f"API响应: {data}")
                    
                    if data.get("code") == 200 and "result" in data:
                        result = data["result"]
                        game_id = result.get("game_id", "")
                        first_idiom = result.get("first_idiom", "")
                        
                        if game_id and first_idiom:
                            # 创建新的游戏会话
                            self.game_sessions[chatroom_id] = GameSession(
                                chatroom_id=chatroom_id,
                                game_id=game_id,
                                current_idiom=first_idiom,
                                active=True,
                                start_time=time.time(),
                                last_activity_time=time.time(),
                                used_idioms=[first_idiom]  # 记录第一个成语
                            )
                            
                            # 创建或清空错误记录
                            if chatroom_id not in self.error_records:
                                self.error_records[chatroom_id] = {}
                            else:
                                self.error_records[chatroom_id].clear()
                            
                            # 发送游戏开始消息
                            mode_text = "相同尾字模式" if self.mode == "exact" else "同音模式"
                            end_command = self.end_commands[0] if self.end_commands else "游戏结束"
                            repeat_rule = "允许使用用过的成语" if self.allow_repeat else "不允许使用用过的成语"
                            await bot.send_text_message(
                                chatroom_id,
                                f"🎮 成语接龙游戏开始！({mode_text})\n"
                                f"⏱️ 每轮限时 {self.round_timeout} 秒\n"
                                f"🎯 第一个成语：{first_idiom}\n"
                                f"📝 发送\"{end_command}\"可以手动结束游戏\n"
                                f"💡 游戏规则：{repeat_rule}\n"
                                f"请接龙！"
                            )
                            logger.info(f"群 {chatroom_id} 开始成语接龙游戏，首个成语：{first_idiom}")
                            
                            # 保存会话数据
                            if self.enable_persistence:
                                self._save_sessions()
                                
                            return
                        else:
                            logger.error(f"API响应缺少必要字段: {result}")
                    else:
                        logger.error(f"API响应错误: {data}")
            
            # 如果执行到这里，说明API调用失败
            await bot.send_text_message(chatroom_id, "❌ 游戏开始失败，请稍后再试")
            
        except Exception as e:
            logger.error(f"开始成语接龙游戏时出错: {str(e)}")
            await bot.send_text_message(chatroom_id, "❌ 游戏开始失败，请稍后再试")
    
    async def _handle_idiom(self, bot: WechatAPIClient, message: dict):
        """处理玩家接龙"""
        content = str(message.get("Content", "")).strip()
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        
        # 获取游戏会话
        game_session = self.game_sessions.get(from_wxid)
        if not game_session or not game_session.active:
            return
        
        # 输入长度预判断
        if len(content) < 2 or len(content) > 10:
            await self._send_error_message(
                bot, 
                from_wxid, 
                sender_wxid, 
                "输入太短" if len(content) < 2 else "输入太长",
                game_session.current_idiom
            )
            return
        
        # 首字匹配检查（仅在exact模式下）
        if self.local_check and self.mode == "exact" and game_session.current_idiom:
            current_last_char = game_session.current_idiom[-1]
            input_first_char = content[0]
            
            if current_last_char != input_first_char:
                await self._send_error_message(
                    bot, 
                    from_wxid, 
                    sender_wxid, 
                    f"接龙错误，成语必须以\"{current_last_char}\"开头",
                    game_session.current_idiom
                )
                return
        
        # 重复成语检查
        if not self.allow_repeat and content in game_session.used_idioms:
            await self._send_error_message(
                bot, 
                from_wxid, 
                sender_wxid, 
                f"\"{content}\"已经被使用过了，请换一个",
                game_session.current_idiom
            )
            return
        
        try:
            # 调用API验证接龙
            async with aiohttp.ClientSession() as http_session:
                params = {
                    "AppSecret": self.app_secret,
                    "game_id": game_session.game_id,
                    "idiom": content
                }
                
                if self.debug_mode:
                    logger.debug(f"发起接龙验证API请求: {self.api_url}，参数: {params}")
                
                async with http_session.get(self.api_url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"API请求失败，状态码: {response.status}")
                        return
                    
                    try:
                        data = await response.json()
                    except Exception as e:
                        logger.error(f"解析API响应JSON失败: {str(e)}")
                        return
                    
                    if self.debug_mode:
                        logger.debug(f"API响应: {data}")
                    
                    # 接龙成功
                    if data.get("code") == 200 and "result" in data:
                        result = data["result"]
                        next_idiom = result.get("next_idiom", "")
                        
                        if next_idiom:
                            await self._handle_success(bot, game_session, from_wxid, sender_wxid, content, next_idiom)
                            
                            # 保存会话数据
                            if self.enable_persistence:
                                self._save_sessions()
                                
                            return
                    
                    # 接龙失败
                    error_msg = data.get("msg", "接龙失败")
                    await self._handle_failure(bot, from_wxid, sender_wxid, content, error_msg, game_session.current_idiom)
            
        except Exception as e:
            logger.error(f"处理成语接龙时出错: {str(e)}")
    
    async def _handle_success(self, bot: WechatAPIClient, game_session: GameSession, 
                             from_wxid: str, sender_wxid: str, content: str, next_idiom: str):
        """处理接龙成功"""
        # 更新游戏状态
        game_session.current_idiom = next_idiom
        game_session.last_activity_time = time.time()
        game_session.reminder_sent = False
        
        # 记录已使用的成语
        game_session.used_idioms.append(content)
        game_session.used_idioms.append(next_idiom)
        
        # 计算积分
        points = self.base_points
        consecutive_bonus = 0
        
        # 检查是否是连续接龙
        if game_session.last_player == sender_wxid:
            game_session.consecutive_players[sender_wxid] = game_session.consecutive_players.get(sender_wxid, 0) + 1
            consecutive_bonus = game_session.consecutive_players[sender_wxid] * self.bonus_points
        else:
            game_session.consecutive_players[sender_wxid] = 1
        
        # 更新总接龙次数
        game_session.total_idioms_count[sender_wxid] = game_session.total_idioms_count.get(sender_wxid, 0) + 1
        
        # 更新玩家积分
        total_points = points + consecutive_bonus
        game_session.players[sender_wxid] = game_session.players.get(sender_wxid, 0) + total_points
        game_session.last_player = sender_wxid
        
        # 添加积分到数据库
        if HAS_ADMIN_POINT:
            try:
                admin_point = AdminPoint()
                admin_point.db.add_points(sender_wxid, total_points)
                if self.debug_mode:
                    logger.debug(f"已为玩家 {sender_wxid} 添加 {total_points} 积分")
            except Exception as e:
                logger.error(f"添加积分到数据库时出错: {str(e)}")
        
        # 获取玩家昵称
        try:
            nickname = await bot.get_nickname(sender_wxid)
            if not nickname:
                nickname = sender_wxid
        except Exception as e:
            logger.error(f"获取玩家昵称时出错: {str(e)}")
            nickname = sender_wxid
        
        # 发送接龙成功消息
        consecutive_text = f"，连续接龙 {game_session.consecutive_players[sender_wxid]} 次" if game_session.consecutive_players[sender_wxid] > 1 else ""
        bonus_text = f"，额外奖励 {consecutive_bonus} 积分" if consecutive_bonus > 0 else ""
        
        await bot.send_text_message(
            from_wxid,
            f"✅ {nickname} 接龙成功！\n"
            f"🎯 {content} ➡️ {next_idiom}\n"
            f"💰 获得 {points} 积分{consecutive_text}{bonus_text}\n"
            f"请继续接龙！"
        )
        logger.info(f"玩家 {sender_wxid} 接龙成功: {content} -> {next_idiom}")
    
    async def _handle_failure(self, bot: WechatAPIClient, from_wxid: str, 
                             sender_wxid: str, content: str, error_msg: str, current_idiom: str):
        """处理接龙失败"""
        if not self.show_error_tips:
            return
        
        # 生成具体的错误提示
        error_tip = error_msg
        if "必须以" in error_msg or "开头" in error_msg:
            last_char = current_idiom[-1]
            error_tip = f"接龙错误，成语必须以\"{last_char}\"开头"
        elif "成语不存在" in error_msg:
            error_tip = f"\"{content}\"不是成语，请重新输入"
        elif "已被使用" in error_msg or "已经用过" in error_msg:
            error_tip = f"\"{content}\"已经被使用过了，请换一个"
        
        await self._send_error_message(bot, from_wxid, sender_wxid, error_tip, current_idiom)
    
    async def _send_error_message(self, bot: WechatAPIClient, from_wxid: str, 
                                 sender_wxid: str, error_tip: str, current_idiom: str):
        """发送错误消息，带冷却控制"""
        # 检查冷却时间
        current_time = time.time()
        last_error_time = self.error_records.get(from_wxid, {}).get(sender_wxid, 0)
        
        if current_time - last_error_time <= self.error_cooldown:
            return
        
        # 获取玩家昵称
        try:
            nickname = await bot.get_nickname(sender_wxid)
            if not nickname:
                nickname = sender_wxid
        except Exception as e:
            logger.error(f"获取玩家昵称时出错: {str(e)}")
            nickname = sender_wxid
        
        # 发送错误提示
        await bot.send_text_message(
            from_wxid,
            f"❌ {nickname}，{error_tip}\n"
            f"当前成语：{current_idiom}"
        )
        
        # 更新错误记录
        if from_wxid not in self.error_records:
            self.error_records[from_wxid] = {}
        self.error_records[from_wxid][sender_wxid] = current_time
    
    async def _end_game(self, bot: WechatAPIClient, chatroom_id: str):
        """结束游戏"""
        game_session = self.game_sessions.get(chatroom_id)
        if not game_session:
            logger.warning(f"尝试结束不存在的游戏会话: {chatroom_id}")
            return
        
        try:
            # 标记游戏为非活动状态
            game_session.active = False
            
            # 保存会话数据（虽然游戏结束了，但保存一下可以记录最终状态）
            if self.enable_persistence:
                self._save_sessions()
            
            # 计算游戏时长
            duration = int(time.time() - game_session.start_time)
            minutes, seconds = divmod(duration, 60)
            
            # 生成排行榜
            if game_session.players:
                # 按积分排序
                sorted_players = sorted(game_session.players.items(), key=lambda x: x[1], reverse=True)
                
                # 生成积分排行榜文本
                points_leaderboard = "🏆 积分排行榜：\n"
                for i, (wxid, points) in enumerate(sorted_players, 1):
                    try:
                        nickname = await bot.get_nickname(wxid)
                        if not nickname:
                            nickname = wxid
                    except Exception as e:
                        logger.error(f"获取玩家昵称时出错: {str(e)}")
                        nickname = wxid
                    
                    points_leaderboard += f"{i}. {nickname}: {points} 积分\n"
                
                # 按接龙成功次数排序
                sorted_by_counts = sorted(game_session.total_idioms_count.items(), key=lambda x: x[1], reverse=True)
                
                # 生成成功次数排行榜文本
                counts_leaderboard = "🔄 接龙次数排行榜：\n"
                for i, (wxid, count) in enumerate(sorted_by_counts, 1):
                    try:
                        nickname = await bot.get_nickname(wxid)
                        if not nickname:
                            nickname = wxid
                    except Exception as e:
                        logger.error(f"获取玩家昵称时出错: {str(e)}")
                        nickname = wxid
                    
                    counts_leaderboard += f"{i}. {nickname}: 成功接龙 {count} 次\n"
                
                # 发送游戏结束消息
                used_idioms_count = len(game_session.used_idioms)
                end_message = (
                    f"🎮 成语接龙游戏结束！\n"
                    f"⏱️ 游戏时长: {minutes}分{seconds}秒\n"
                    f"🔢 共有 {len(game_session.players)} 人参与\n"
                    f"📚 共接龙 {used_idioms_count//2} 轮\n\n"
                    f"{counts_leaderboard}\n"
                    f"{points_leaderboard}\n"
                    f"发送 \"{self.commands[0]}\" 开始新游戏"
                )
                
                if self.debug_mode:
                    logger.debug(f"发送游戏结束消息: {end_message}")
                
                await bot.send_text_message(chatroom_id, end_message)
            else:
                # 如果没有人参与
                end_message = (
                    f"🎮 成语接龙游戏结束！\n"
                    f"😢 没有人参与游戏\n"
                    f"发送 \"{self.commands[0]}\" 开始新游戏"
                )
                await bot.send_text_message(chatroom_id, end_message)
            
            logger.info(f"群 {chatroom_id} 的成语接龙游戏结束，游戏时长: {minutes}分{seconds}秒")
            
        except Exception as e:
            logger.error(f"结束成语接龙游戏时出错: {str(e)}")
        finally:
            # 确保清理游戏会话，即使发生异常
            if self.debug_mode:
                logger.debug(f"清理游戏会话: {chatroom_id}")
            
            if chatroom_id in self.game_sessions:
                del self.game_sessions[chatroom_id]
            # 清理错误记录
            if chatroom_id in self.error_records:
                del self.error_records[chatroom_id]
    
    async def unload(self):
        """插件卸载时调用，清理资源"""
        # 结束所有游戏会话
        bot = None
        try:
            # 尝试直接从sys.modules获取bot实例
            import sys
            for name, module in sys.modules.items():
                if hasattr(module, 'bot'):
                    bot = getattr(module, 'bot')
                    break
            
            if bot and hasattr(self, 'game_sessions'):
                for chatroom_id, session in list(self.game_sessions.items()):
                    if session.active:
                        try:
                            await self._end_game(bot, chatroom_id)
                        except Exception as e:
                            logger.error(f"卸载插件时结束游戏出错: {str(e)}")
            
            # 保存会话数据
            if self.enable_persistence:
                self._save_sessions()
                
            logger.success("成语接龙插件已卸载")
        except Exception as e:
            logger.error(f"卸载成语接龙插件时出错: {str(e)}") 