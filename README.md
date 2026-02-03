# 🤖 Numbers Math Bot

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)
![aiogram](https://img.shields.io/badge/aiogram-3.17.0-9cf.svg)

A Telegram bot designed to help 3rd-grade students (ages 8-9) practice mental arithmetic through adaptive math problems with gamification elements.

## ✨ Key Features

- 🎯 **Adaptive Difficulty**: 5 progressive levels that adjust based on user performance
- 🧮 **Smart Expression Generation**: Pedagogically-appropriate math problems with constraints
- 🏆 **Gamification System**: Points, encouraging feedback, and progress tracking
- 🔄 **Three Attempts**: Multiple chances per problem with diminishing rewards
- 📊 **Progress Tracking**: Automatic difficulty increases every 10 points (0-49 range)
- 🎮 **Engaging Interface**: Emojis and positive reinforcement for kids
- 🐳 **Docker Ready**: Easy deployment with containerized architecture
- 💾 **State Persistence**: Redis storage with automatic fallback to memory
- 📝 **Comprehensive Logging**: Structured logging for monitoring and debugging
- ✅ **Type Safe**: Fully typed with Pylance/VSCode IDE support

## 🎓 How It Works

### Problem Generation

The bot generates math problems tailored for 3rd-grade students with these constraints:

- **Number Range**: Integers from 0 to 1000
- **Operations**: Addition, subtraction, multiplication, and limited division
- **Multiplication**: One factor always ≤ 10 for mental calculation
- **Division**: Only integer results (no remainders)
- **Intermediate Results**: Always positive, never negative
- **Structure Complexity**: Progresses from simple to multi-step expressions with parentheses

### Difficulty Levels

```
Level 0 (0-9 points)    → Most complex (up to 5 operations with parentheses)
Level 1 (10-19 points)  → High complexity (4 operations, some parentheses)
Level 2 (20-29 points)  → Medium complexity (3 operations)
Level 3 (30-39 points)  → Lower complexity (2 operations)
Level 4 (40-49 points)  → Simple (1-2 operations)
```

### Scoring System

- ✅ **Correct Answer**: +1 point
- ❌ **Wrong Answer (after 3 attempts)**: -1 point
- 🎯 **Progression**: Difficulty decreases as points increase (makes problems easier)
- 📉 **Regression**: Difficulty increases when points decrease (makes problems harder)

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for container deployment)
- Redis (optional, falls back to memory storage)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)

### Docker Deployment (Recommended)

1. **Clone the repository**
   ```bash
   git clone https://github.com/Evgeny105/numbers.git
   cd numbers
   ```

2. **Create environment file**
   ```bash
   echo "TOKEN_API_BOT=<your_bot_token>" > .env
   echo "REDIS=localhost:6379" >> .env
   ```

3. **Build and run**
   ```bash
   docker compose up --build -d
   ```

4. **View logs**
   ```bash
   docker logs -f math-bot-container
   ```

### Local Development

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set environment variables**
   ```bash
   export TOKEN_API_BOT=<your_bot_token>
   export REDIS=localhost:6379  # Optional
   export LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
   ```

3. **Run the bot**
   ```bash
   python bot.py
   ```

## 📋 Configuration

### Environment Variables

| Variable        | Required | Default | Description                                                       |
| --------------- | -------- | ------- | ----------------------------------------------------------------- |
| `TOKEN_API_BOT` | ✅ Yes    | -       | Telegram bot token from @BotFather                                |
| `REDIS`         | ❌ No     | -       | Redis connection URL (format: `host:port` or `redis://host:port`) |
| `LOG_LEVEL`     | ❌ No     | `INFO`  | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)               |

### Redis Configuration

The bot supports Redis for persistent state storage across restarts. If Redis is unavailable, the bot automatically falls back to in-memory storage (user progress resets on restart).

**Examples:**
```bash
# Simple connection
REDIS=localhost:6379

# Full URL with protocol
REDIS=redis://localhost:6379/0

# With password
REDIS=redis://:password@localhost:6379
```

## 🏗️ Architecture

```
┌─────────────┐
│   Telegram  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│          bot.py (Main)           │
│  - Command handlers              │
│  - Message handlers              │
│  - User interaction logic        │
└──────┬──────────┬───────────────┘
       │          │
       │          ▼
       │  ┌─────────────────────────┐
       │  │   gen.py (Engine)     │
       │  │  - Expression gen     │
       │  │  - Constraint check    │
       │  └─────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         states.py                │
│  - FSM state definitions        │
│  - User session states         │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│    redis_handlers.py            │
│  - Redis initialization        │
│  - Storage configuration      │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         Storage Backend           │
│  Redis (persistent)            │
│  Memory (fallback)             │
└─────────────────────────────────────┘
```

## 📂 Project Structure

```
numbers/
├── bot.py                # Main bot logic and handlers
├── gen.py                # Math expression generation engine
├── states.py             # FSM state definitions
├── redis_handlers.py     # Redis storage initialization
├── requirements.txt      # Python dependencies
├── Dockerfile           # Container definition
├── docker-compose.yml    # Multi-container setup
├── .env                # Environment variables (create manually)
├── .gitignore         # Git ignore patterns
├── README.md           # This file
└── memory-bank/       # Project documentation
    ├── projectbrief.md
    ├── productContext.md
    ├── systemPatterns.md
    ├── techContext.md
    ├── activeContext.md
    ├── progress.md
    └── library-docs.md
```

## 🎮 User Commands

| Command  | Description                     |
| -------- | ------------------------------- |
| `/start` | Start the bot or resume session |
| `/stop`  | End session and clear progress  |

## 🔧 Development

### Tech Stack

- **Framework**: aiogram 3.17.0 (Telegram Bot API wrapper)
- **Storage**: Redis with Memory fallback
- **Language**: Python 3.11+
- **Type Checking**: Pylance (VSCode)
- **Container**: Docker & Docker Compose

### Adding Features

The codebase is well-documented and type-annotated. Key modules:

- **`bot.py`**: All Telegram interaction logic
- **`gen.py`**: Expression generation algorithms
- **`states.py`**: FSM state management
- **`redis_handlers.py`**: Storage layer abstraction

See `memory-bank/library-docs.md` for aiogram 3.17.0 API reference.

### Code Quality

- ✅ Full type annotations for IDE support
- ✅ Comprehensive docstrings for all functions
- ✅ Proper async/await patterns
- ✅ Graceful error handling
- ✅ Input validation and sanitization
- ✅ AST-based safe expression evaluation

## 🐳 Docker Operations

### Build and Start
```bash
docker compose up --build -d
```

### Stop
```bash
docker compose down
```

### Rebuild from Scratch
```bash
docker compose down
docker compose up --build -d
```

### View Logs
```bash
docker logs -f math-bot-container
```

### Restart
```bash
docker compose restart
```

## 📊 Monitoring

The bot provides structured logging accessible via Docker logs:

```bash
docker logs -f math-bot-container | grep "INFO"
```

Log levels:
- `DEBUG`: Detailed diagnostic information
- `INFO`: Normal operational messages
- `WARNING`: Warning messages for non-critical issues
- `ERROR`: Error messages for failures

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style

- Follow existing code structure and patterns
- Add type annotations to all new functions
- Include docstrings with Args, Returns sections
- Use Russian for user-facing text
- Maintain existing error handling patterns

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [aiogram](https://github.com/aiogram/aiogram) - Modern async Telegram bot framework
- Inspired by educational apps that make learning fun
- For the young mathematicians who inspire this project

## 📞 Support

For issues, questions, or suggestions:
- Open an issue on [GitHub](https://github.com/Evgeny105/numbers/issues)
- Contact the maintainers

---

**Made with ❤️ for young mathematicians**