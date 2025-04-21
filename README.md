# 成语接龙插件

## 📝 插件介绍

这是一个为 xxxbot-pad 开发的成语接龙插件，玩家需要根据上一个成语的最后一个字来接新的成语。游戏支持两种模式：相同尾字模式（默认）和同音模式。玩家成功接龙可以获得积分奖励，连续接龙还有额外积分奖励。

## ✨ 主要功能

- 🔄 **成语接龙游戏**：根据上一个成语的最后一个字接新成语
- 🌟 **积分奖励**：成功接龙获得积分，连续接龙有额外奖励
- 🔍 **两种接龙模式**：
  - ✅ **相同尾字模式**：新成语的第一个字必须与上一个成语的最后一个字相同
  - 🔊 **同音模式**：新成语的第一个字必须与上一个成语的最后一个字发音相同
- ⏱️ **时间限制**：一定时间内无人接龙，游戏自动结束
- 🔔 **提醒功能**：快要超时时会有提醒

## 🚀 使用方法

1. 在群聊中发送以下任一命令启动游戏：
   - `成语接龙`
   - `接龙游戏`
   - `开始接龙`

2. 机器人会开始游戏并给出第一个成语
3. 群成员直接在群里发送接龙的成语
4. 如果成功接龙，机器人会给予积分奖励
5. 游戏一直持续，直到规定时间内无人接龙

## ⚙️ 配置说明

配置文件位于 `plugins/IdiomSolitaire/config.toml`，主要配置项包括：

```toml
[IdiomSolitaire]
# 插件基本设置
enable = true
commands = ["成语接龙", "接龙游戏", "开始接龙"]
end-commands = ["游戏结束", "结束接龙", "结束游戏"] # 结束游戏的命令
command-tip = "发送\"成语接龙\"开始游戏"

# 游戏设置
round-timeout = 60  # 每轮游戏超时时间(秒)，超时后游戏自动结束
reminder-time = 30   # 提醒时间(秒)，剩余多少秒提醒用户
mode = "exact"       # 接龙模式: exact(相同尾字)或pinyin(同音)
allow-repeat = false # 是否允许使用重复的成语，设为false则每轮游戏中成语不能重复使用

# 本地判断设置
local-check = true   # 是否在请求API前进行本地判断，仅在mode为exact时有效
cache-used-idioms = true  # 是否缓存已使用成语，用于本地判断

# API设置
api-url = "https://api.dudunas.top/api/chengyujielong"
app-secret = ""   # 替换为实际的AppSecret

# 积分设置
base-points = 5      # 每次接龙成功获得的基础积分
bonus-points = 2     # 连续接龙额外奖励积分

# 调试设置
debug-mode = false   # 调试模式
```

## 🔄 依赖关系

- **积分系统**：需要 XYBotDB 支持积分奖励功能
- **昵称显示**：使用 contacts.db 数据库获取用户昵称显示

## 📊 API接口说明

插件使用以下API接口获取成语和验证接龙：

```
https://api.dudunas.top/api/chengyujielong
```

参数说明：
- `start`：是否开始游戏（true或不传）
- `mode`：接龙模式（exact或pinyin）
- `game_id`：游戏ID，开始游戏时获得
- `idiom`：接龙的成语
- `AppSecret`：API访问密钥

返回格式：
```json
// 开始游戏
{
  "code": 200,
  "msg": "Game started successfully",
  "result": {
    "game_id": "39a38b0e196d116831c175358996f90b",
    "first_idiom": "四方八面"
  }
}

// 接龙成功
{
  "code": 200,
  "msg": "Success",
  "result": {
    "next_idiom": "砥砺琢磨"
  }
}
```

## 🛠️ 版本信息

- **版本**：1.0.0
- **开发者**：wspzf 