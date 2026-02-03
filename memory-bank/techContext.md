# Technical Context - Numbers Math Bot

## Technology Stack

### Core Framework
- **Python 3.11**: Primary programming language
- **aiogram 3.17.0**: Telegram bot framework with async support
- **asyncio**: Asynchronous programming for concurrent operations

### Storage & Persistence
- **Redis 5.2.1**: Primary storage for user state and session data
- **aiogram FSM**: Built-in memory storage as fallback
- **Environment Variables**: Configuration management

### Deployment & Infrastructure
- **Docker**: Containerization for consistent deployment
- **Docker Compose**: Multi-container orchestration
- **Multi-stage builds**: Optimized production images

### Development Dependencies
```
aiofiles==24.1.0           # Async file operations
aiogram==3.17.0            # Telegram bot framework
aiohappyeyeballs==2.4.4   # Happy eyeballs algorithm
aiohttp==3.11.11          # Async HTTP client
aiosignal==1.3.2          # Async signaling
annotated-types==0.7.0    # Type annotations support
attrs==25.1.0              # Class attributes
certifi==2025.1.31         # SSL certificates
frozenlist==1.5.0          # Immutable list implementation
idna==3.10                 # Internationalized domain names
magic-filter==1.0.12       # Message filtering
multidict==6.1.0           # Multi-dictionary implementation
propcache==0.2.1           # Property caching
pydantic==2.10.6           # Data validation
pydantic_core==2.27.2      # Pydantic core
redis==5.2.1               # Redis client
typing_extensions==4.12.2   # Type extensions
yarl==1.18.3               # URL parsing
```

## Development Environment

### Environment Variables
```bash
# Required
TOKEN_API_BOT=<telegram_bot_token>
REDIS=<redis_connection_url>

# Optional
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Project Structure
```
numbers/
├── bot.py              # Main bot logic and handlers
├── gen.py              # Math expression generator
├── states.py           # FSM state definitions
├── redis_handlers.py   # Redis storage configuration
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container configuration
├── docker-compose.yml  # Multi-container setup
├── .env               # Environment variables (local)
└── memory-bank/       # Project documentation
```

## Bot Architecture

### aiogram Framework Integration
```python
# Core initialization pattern
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

# Bot configuration
bot = Bot(TOKEN_API, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = init_redis()  # Redis or Memory fallback
dp = Dispatcher(storage=storage)
```

### Handler Registration
- **Command Handlers**: `/start`, `/stop`
- **State Handlers**: Answer handlers for each attempt state
- **Fallback Handler**: Catch-all for unexpected messages

### Message Processing Pipeline
1. **Telegram → aiogram**: Raw message reception
2. **Dispatcher**: Routes to appropriate handler
3. **Handler Logic**: Process user input, update state
4. **Storage**: Persist state changes
5. **Response**: Send formatted reply to Telegram

## State Management Implementation

### FSM Storage Backends
```python
# Redis storage (production)
storage = RedisStorage.from_url(redis_url)

# Memory storage (development/fallback)
storage = MemoryStorage()
```

### State Data Structure
```python
# User session data stored in FSM
{
    "user_id": int,
    "chat_id": int,
    "state": UserStates,
    "data": {
        "difficulty": int,     # 0-4
        "points": int,         # 0-49
        "expression": str,
        "answer": int,
        "user_name": str
    }
}
```

### State Persistence
- **Redis**: Production deployment with persistence
- **Memory**: Development and Redis failure scenarios
- **Automatic Fallback**: Seamless transition between backends

## Expression Generation Engine

### Core Algorithm Design
```python
# Recursive expression generation with constraint validation
def generate_expression(depth=0):
    if depth >= MAX_DIFICULTY:
        return generate_simple_expression()
    
    # Generate sub-expressions
    expr1 = generate_expression(depth + 1)
    expr2 = generate_expression(depth + 1)
    
    # Combine with constraint checking
    for op in random.sample(operations, k=len(operations)):
        result = combine_expressions(expr1, expr2, op)
        if validate_constraints(result):
            return result
```

### AST-Based Validation
```python
import ast

# Safe expression evaluation without security risks
def check_intermediate_results(expression):
    tree = ast.parse(expression, mode="eval")
    # Walk AST checking constraints at each node
    # Validates: no negatives, integer division, multiplication limits
```

### Constraint Implementation
- **Negative Prevention**: AST evaluation checks for negative results
- **Multiplication Limits**: At least one factor ≤ 10
- **Integer Division**: Ensures no remainder in division operations
- **Range Validation**: All numbers 0-1000, final result positive integer

## Storage Implementation

### Redis Configuration
```python
def init_redis() -> RedisStorage:
    redis_urls = getenv("REDIS").split(",")
    
    if len(redis_urls) == 1:
        # Single Redis instance
        full_url = f"redis://{redis_urls[0]}"
        return RedisStorage.from_url(full_url)
    else:
        # Multiple URLs not supported
        raise ValueError("Multiple Redis URLs not supported")
```

### Data Serialization
- **aiogram Built-in**: Automatic JSON serialization for FSM data
- **Schema Validation**: Pydantic models ensure data consistency
- **Error Handling**: Graceful degradation on storage failures

### Connection Management
- **Connection Pooling**: Efficient Redis connection reuse
- **Retry Logic**: Automatic reconnection on connection loss
- **Health Monitoring**: Connection status logging

## Container Configuration

### Multi-stage Docker Build
```dockerfile
# Stage 1: Build dependencies
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
CMD ["python", "bot.py"]
```

### Docker Compose Setup
```yaml
version: '3.8'
services:
  math-bot:
    build: .
    restart: always
    environment:
      - TOKEN_API_BOT=${TOKEN_API_BOT}
      - REDIS=redis:6379
    depends_on:
      - redis
  
  redis:
    image: redis:7-alpine
    restart: always
```

## Deployment Patterns

### Production Environment
- **Container Orchestration**: Docker Compose for service management
- **Service Discovery**: Redis service dependency management
- **Health Checks**: Container restart policies
- **Log Aggregation**: Centralized logging through Docker

### Environment Configuration
```bash
# Production deployment
sudo docker compose up --build -d

# Log monitoring
sudo docker logs -f math-bot-container

# Service restart
sudo docker compose restart
```

## Performance Considerations

### Async Architecture Benefits
- **Non-blocking I/O**: Concurrent user handling
- **Message Queuing**: Prevents response delays
- **Resource Efficiency**: Minimal CPU/memory usage per user

### Memory Management
- **Bounded Recursion**: Limited expression depth prevents stack overflow
- **Data Capping**: Points capped at 49 prevents integer issues
- **Connection Reuse**: Redis connection pooling

### Scalability Patterns
- **Stateless Design**: Bot logic independent of storage backend
- **Horizontal Scaling**: Multiple bot instances possible with shared Redis
- **Load Distribution**: aiogram handles concurrent message processing

## Security Considerations

### Input Validation
```python
# Sanitize user input
ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")

# Safe expression evaluation
tree = ast.parse(expression, mode="eval")  # No exec() usage
```

### Data Privacy
- **Minimal Data Collection**: Only essential user information
- **No Persistent Personal Data**: Session-only storage
- **Secure Token Handling**: Environment variable protection

### Access Control
- **Telegram Authentication**: Built-in user verification
- **Rate Limiting**: Natural rate limiting through state machine
- **Error Information**: No sensitive data in error messages

## Monitoring & Observability

### Logging Strategy
```python
# Structured logging with context
_LOGGER = logging.getLogger(__name__)
_LOGGER.info(f"Пользователь {user_name} решил пример с первой попытки")
```

### Error Tracking
- **Exception Logging**: Comprehensive error capture
- **Fallback Monitoring**: Redis failure detection
- **User Action Tracking**: Problem attempts and outcomes

### Health Metrics
- **Connection Status**: Redis connectivity monitoring
- **User Activity**: Active session tracking
- **System Resources**: Memory and CPU usage

## Development Workflow

### Local Development
```bash
# Setup environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file
echo "TOKEN_API_BOT=your_token" > .env
echo "REDIS=localhost:6379" >> .env

# Run locally
python bot.py
```

### Testing Strategy
- **Manual Testing**: Telegram interaction testing
- **Unit Testing**: Expression generation validation
- **Integration Testing**: Redis connectivity and FSM operations
- **Container Testing**: Docker build and deployment verification