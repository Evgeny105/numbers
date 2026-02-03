# System Patterns - Numbers Math Bot

## System Architecture

### High-Level Architecture
```
Telegram Platform ↔ aiogram Bot ↔ State Management ↔ Expression Generator
                              ↓
                         Storage Layer (Redis/Memory)
                              ↓
                         Logging System
```

### Core Components
- **Bot Layer** (`bot.py`): Telegram interface and user interaction handlers
- **State Management** (`states.py`): FSM for user session states
- **Expression Engine** (`gen.py`): Mathematical problem generation with constraints
- **Storage Layer** (`redis_handlers.py`): Persistent user data with fallback
- **Logging**: Comprehensive error tracking and user activity monitoring

## State Management Patterns

### Finite State Machine (FSM)
The bot uses aiogram's FSM to manage user interaction states:

```python
class UserStates(StatesGroup):
    solved = State()           # Problem solved, ready for next
    await_1_answer = State()   # First attempt
    await_2_answer = State()   # Second attempt  
    await_3_answer = State()   # Final attempt
```

### State Transitions
```
/start → await_1_answer → [correct] → solved → await_1_answer
                     → [incorrect] → await_2_answer → [correct] → solved
                                          → [incorrect] → await_3_answer → [correct] → solved
                                                          → [incorrect] → solved (with penalty)
```

### User Data Schema
```python
{
    "difficulty": int,        # 0-4, determines expression complexity
    "points": int,           # 0-49, affects difficulty level
    "expression": str,       # Current math problem
    "answer": int,          # Correct answer to current problem
    "user_name": str        # Telegram user's full name
}
```

## Expression Generation Patterns

### Difficulty Algorithm
- **Inverted Difficulty**: `difficulty=0` = hardest, `difficulty=4` = easiest
- **Depth Calculation**: `depth = MAX_DIFICULTY - difficulty`
- **Complexity Control**: Depth limits recursion in expression generation

### Constraint Enforcement
The generator enforces pedagogical constraints through AST validation:

```python
# Core constraints checked during generation:
- No negative intermediate results
- Multiplication: at least one factor ≤ 10
- Division: must be integer-only
- All numbers: 0-1000 range
- Final result: positive integer
```

### Expression Building Pattern
```python
# Recursive generation with constraint validation
def generate_expression(depth):
    if depth >= MAX_DIFICULTY:
        return generate_simple_expression()
    
    expr1 = generate_expression(depth + 1)
    expr2 = generate_expression(depth + 1)
    
    # Try operations in random order until constraints satisfied
    for op in random.sample(["+", "-", "*", "/"], k=4):
        new_expr = combine_expressions(expr1, expr2, op)
        if new_expr and check_intermediate_results(new_expr.expr):
            return new_expr
    
    return generate_simple_expression()
```

### Priority-Aware Parentheses
The system correctly handles operator precedence:
```python
# Parentheses added when child priority < parent priority
# Example: (a + b) * c needs parentheses, a + b * c doesn't
def maybe_parenthesize(expr, parent_priority):
    if expr.priority.value < parent_priority.value:
        return f"({expr.expr})"
    return expr.expr
```

## Scoring and Difficulty Patterns

### Points System
```python
def add_points(state):
    points = min(points + 1, 49)  # Cap at 49
    difficulty = points // 10      # 0-4 difficulty levels
    state.update_data(points=points, difficulty=difficulty)

def subtract_points(state):
    points = max(points - 1, 0)    # Floor at 0
    difficulty = points // 10
    state.update_data(points=points, difficulty=difficulty)
```

### Difficulty Progression
- **Level 0** (0-9 points): Most complex expressions (depth 5)
- **Level 1** (10-19 points): Complex expressions (depth 4)
- **Level 2** (20-29 points): Moderate complexity (depth 3)
- **Level 3** (30-39 points): Simple expressions (depth 2)
- **Level 4** (40-49 points): Basic operations (depth 1)

## Error Handling Patterns

### Graceful Degradation
```python
# Redis failure → Memory storage fallback
try:
    storage = init_redis()
except Exception as e:
    storage = MemoryStorage()  # Automatic fallback
```

### Input Validation
```python
# Flexible number input handling
ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
try:
    ans = float(ans)  # Convert to number
except:
    # Prompt for proper number input
```

### State Recovery
```python
# Prevent state corruption with try-catch blocks
try:
    data = await state.get_data()
    points = data.get("points", 0)
except:
    await state.update_data(difficulty=0, points=0)  # Reset to defaults
```

## Logging Patterns

### Structured Logging
```python
# Key events tracked:
- New user registration
- Problem attempts and results
- Difficulty level changes
- Error conditions and recoveries
- System initialization/failures
```

### Log Levels
- **INFO**: User actions, progress updates, system status
- **ERROR**: Failures, fallbacks, unexpected conditions
- **WARNING**: Non-critical issues, degraded operation

## Message Handling Patterns

### Async Message Queue
All message sends use `asyncio.create_task()` to prevent blocking:
```python
asyncio.create_task(message_answer(message, text))
asyncio.create_task(state.update_data(...))
```

### Response Categorization
- **Success Messages**: Celebratory, use multiple emojis
- **Correction Messages**: Gentle, encouraging, include original problem
- **Error Messages**: Clear instructions, friendly tone
- **System Messages**: Informative, minimal jargon

### Message Formatting
```python
# Consistent message structure:
f"🔔 Внимание-внимание! Новый примерчик! 🔔\n"
f"<code>{expression}</code>\n"
"Скорее пиши ответ! ⏱️"
```

## Storage Patterns

### Redis Integration
```python
# Environment-based Redis configuration
redis_urls = getenv("REDIS").split(",")
if len(redis_urls) == 1:
    storage = RedisStorage.from_url(f"redis://{redis_urls[0]}")
```

### Data Persistence Strategy
- **Primary**: Redis for production deployment
- **Fallback**: In-memory storage for development/testing
- **Session-based**: User data persists between interactions
- **Privacy**: Only necessary data stored (no sensitive information)

## Performance Patterns

### Non-Blocking Operations
- All I/O operations use async/await
- Message sends queued to prevent response delays
- State updates fire-and-forget where appropriate

### Resource Management
- **Expression Generation**: Bounded recursion prevents stack overflow
- **Points Capping**: Prevents integer overflow (max 49 points)
- **Input Sanitization**: Prevents injection attacks
- **Connection Pooling**: Redis connections managed efficiently

## Deployment Patterns

### Container Strategy
```dockerfile
# Multi-stage build for minimal production image
FROM python:3.11-slim as builder
# ... build stage ...
FROM python:3.11-slim as runtime
# ... runtime stage ...
```

### Environment Configuration
- **Development**: Local Redis, debug logging
- **Production**: Redis cluster, structured logging
- **Configuration via Environment Variables**: No hardcoded secrets

### Health Monitoring
- **Log Aggregation**: All errors centrally logged
- **State Validation**: Periodic checks for corrupted user data
- **Resource Monitoring**: Memory usage, connection counts